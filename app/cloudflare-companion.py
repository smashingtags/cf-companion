#!/usr/bin/python3

from __future__ import print_function
from datetime import datetime

from get_docker_secret import get_docker_secret
import atexit
import docker
import logging
from logging.handlers import RotatingFileHandler
from logging import handlers
import os
import re
import requests
import signal
import sys
import threading
import time
from cloudflare import Cloudflare, APIError as CloudflareAPIError
from urllib.parse import urlparse

DRY_RUN = os.environ.get('DRY_RUN', "FALSE")
DEFAULT_TTL = int(os.environ.get('DEFAULT_TTL', "1"))
ENABLE_DOCKER_POLL = os.environ.get('ENABLE_DOCKER_POLL', "TRUE")
DOCKER_SWARM_MODE = os.environ.get('DOCKER_SWARM_MODE', "FALSE")
ENABLE_TRAEFIK_POLL = os.environ.get('ENABLE_TRAEFIK_POLL', "FALSE")
LOGFILE = os.environ.get('LOG_PATH', "/logs") + '/' + os.environ.get('LOG_FILE', "tcc.log")
LOG_LEVEL = os.environ.get('LOG_LEVEL', "INFO")
LOG_TYPE = os.environ.get('LOG_TYPE', "BOTH")
REFRESH_ENTRIES = os.environ.get('REFRESH_ENTRIES', "FALSE")
if 'TRAEFIK_FILTER' in os.environ:
    TRAEFIK_FILTER = os.environ.get('TRAEFIK_FILTER')
TRAEFIK_FILTER_LABEL = os.environ.get('TRAEFIK_FILTER_LABEL', "traefik.constraint")
TRAEFIK_POLL_SECONDS = int(os.environ.get('TRAEFIK_POLL_SECONDS', "60"))
TRAEFIK_POLL_URL = os.environ.get('TRAEFIK_POLL_URL', None)
TRAEFIK_VERSION = os.environ.get('TRAEFIK_VERSION', "2")
RC_TYPE = os.environ.get('RC_TYPE', "CNAME")
ALLOW_RECORD_TYPE_CHANGE = os.environ.get('ALLOW_RECORD_TYPE_CHANGE', "FALSE")

# A CNAME whose content ends here points at a Cloudflare tunnel. Rewriting one
# as an A record silently takes the hostname off the tunnel and points it at an
# address the tunnel does not serve.
TUNNEL_RECORD_SUFFIX = '.cfargotunnel.com'

# Docker event types and the actions worth reacting to. A standalone daemon
# only ever emits the container type; service exists in Swarm alone.
DOCKER_EVENT_CONTAINER_ACTIONS = ('start',)
DOCKER_EVENT_SERVICE_ACTIONS = ('create', 'update')


# Handle Ctrl C
def signal_handler(signal, frame):
  sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# set up logging
logger = logging.getLogger(__name__)
DEBUG = False
VERBOSE = False
date_fmt = "%Y-%m-%dT%H:%M:%S%z"

if LOG_LEVEL.upper() == "DEBUG":
    logger.setLevel(logging.DEBUG)
    fmt = "%(asctime)s %(levelname)s %(lineno)d | %(message)s"
    DEBUG = True

if LOG_LEVEL.upper() == "VERBOSE":
    logger.setLevel(logging.DEBUG)
    fmt = "%(asctime)s %(levelname)s | %(message)s"
    DEBUG = True
    VERBOSE = True

if LOG_LEVEL.upper() == "NOTICE" or LOG_LEVEL.upper() == "INFO":
    logger.setLevel(logging.INFO)
    fmt = "%(asctime)s %(levelname)s | %(message)s"

if LOG_TYPE.upper() == "CONSOLE" or LOG_TYPE.upper() == "BOTH":
    ch = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(fmt, date_fmt)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

if LOG_TYPE.upper() == "FILE" or LOG_TYPE.upper() == "BOTH":
    fh = handlers.logging.FileHandler(LOGFILE)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

synced_mappings = {}

class RepeatedTimer(threading.Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


def init_doms_from_env():
    RX_DOMS = re.compile('^DOMAIN[0-9]+$', re.IGNORECASE)

    doms = list()
    for k in os.environ:
        if not RX_DOMS.match(k):
            continue

        name = os.environ[k]
        try:
            dom = {
                'name': name,
                'proxied': os.environ.get("{}_PROXIED".format(k), "FALSE").upper() == "TRUE",
                'zone_id': os.environ["{}_ZONE_ID".format(k)],
                'ttl': int(os.environ.get("{}_TTL".format(k), DEFAULT_TTL)),
                'target_domain': os.environ.get("{}_TARGET_DOMAIN".format(k), target_domain),
                'comment': os.environ.get("{}_COMMENT".format(k)),
                'excluded_sub_domains': list(filter(None, os.environ.get("{}_EXCLUDED_SUB_DOMAINS".format(k), "").split(','))),
            }

            doms.append(dom)

        except KeyError as e:
            logger.error("*** ERROR: {} is not set!".format(e))

    for dom in doms:
        logger.debug("Domain Configuration: %s", dom)

    return doms


def init_traefik_from_env():
    TRAEFIK_INCLUDED_HOST = re.compile('^TRAEFIK_INCLUDED_HOST[0-9]+$', re.IGNORECASE)
    TRAEFIK_EXCLUDED_HOST = re.compile('^TRAEFIK_EXCLUDED_HOST[0-9]+$', re.IGNORECASE)

    traefik_included_hosts = list()
    traefik_excluded_hosts = list()
    for k in os.environ:
        if TRAEFIK_INCLUDED_HOST.match(k):
            traefik_included_hosts.append(re.compile(os.environ.get(k)))

        if TRAEFIK_EXCLUDED_HOST.match(k):
            traefik_excluded_hosts.append(re.compile(os.environ.get(k)))

    if len(traefik_included_hosts) > 0:
        logger.debug("Traefik Host Includes")
        for traefik_included_host in traefik_included_hosts:
            logger.debug("  %s", traefik_included_host.pattern)
    else:
        logger.debug("Traefik Host Includes: .*")
        traefik_included_hosts.append(re.compile(".*"))

    if len(traefik_excluded_hosts) > 0:
        logger.debug("Traefik Host Excludes")
        for traefik_excluded_host in traefik_excluded_hosts:
            logger.debug("  %s", traefik_excluded_host.pattern)

    return traefik_included_hosts, traefik_excluded_hosts


def is_domain_excluded(name, dom):
    excluded_sub_domains = dom['excluded_sub_domains']

    for sub_dom in excluded_sub_domains:

        fqdn_with_sub_dom = sub_dom + '.' + dom['name']

        if name.find(fqdn_with_sub_dom) != -1:
            logger.info('Ignoring %s because it falls until excluded sub domain: %s', name, sub_dom)
            return True

    return False


def is_matching(host, regexes):
    for regex in regexes:
        if regex.search(host):
            return True
    return False

def is_tunnel_target(content):
    return (content or '').lower().endswith(TUNNEL_RECORD_SUFFIX)


def record_type_change_refused(name, record, new_type):
    """True when rewriting `record` as `new_type` would change its type.

    Retargeting a record within its own type is this tool's whole job.
    Retyping one is not: it is how four working proxied CNAMEs to a Cloudflare
    tunnel become four dead A records, and nothing about the label that
    triggered the sync said anything about the record type. Retyping therefore
    needs an explicit opt-in.
    """
    existing_type = (getattr(record, 'type', None) or '').upper()
    if not existing_type or existing_type == (new_type or '').upper():
        return False

    if ALLOW_RECORD_TYPE_CHANGE:
        logger.warning("Changing %s from %s to %s because ALLOW_RECORD_TYPE_CHANGE is set",
                       name, existing_type, new_type)
        return False

    if is_tunnel_target(getattr(record, 'content', None)):
        logger.warning("Refusing to convert %s from a %s pointing at a Cloudflare tunnel "
                       "into a %s record. Set ALLOW_RECORD_TYPE_CHANGE=TRUE to permit it.",
                       name, existing_type, new_type)
    else:
        logger.warning("Refusing to change %s from a %s record to a %s record. "
                       "Set ALLOW_RECORD_TYPE_CHANGE=TRUE to permit it.",
                       name, existing_type, new_type)
    return True


def write_record(name, domain_info, data, record=None):
    """The one Cloudflare write gate.

    Every decision about what to write is made before this call, so a dry run
    and a live run reach here having taken the identical path and differ only
    in whether the write is issued.
    """
    if DRY_RUN:
        logger.info("DRY-RUN: %s to Cloudflare %s%s: %s",
                    "POST" if record is None else "PUT",
                    domain_info['zone_id'],
                    "" if record is None else ", record {}".format(record.id),
                    data)
        return

    if record is None:
        cf.dns.records.create(zone_id=domain_info['zone_id'], **data)
        logger.info("Created new record: %s to point to %s", name, domain_info['target_domain'])
    else:
        cf.dns.records.update(zone_id=domain_info['zone_id'], dns_record_id=record.id, **data)
        logger.info("Updated existing record: %s to point to %s", name, domain_info['target_domain'])


# Start Program to update the Cloudflare
def point_domain(name, domain_infos):
    ok = True
    for domain_info in domain_infos:
        if name == domain_info['target_domain']:
            continue

        if name.find(domain_info['name']) < 0:
            continue

        if is_domain_excluded(name, domain_info):
            continue

        records_response = cf.dns.records.list(zone_id=domain_info['zone_id'], name=name)
        records = records_response.result

        data = {
            u'type': RC_TYPE,
            u'name': name,
            u'content': domain_info['target_domain'],
            u'ttl': int(domain_info['ttl']),
            u'proxied': bool(domain_info['proxied']),
            u'comment': domain_info['comment']
        }

        try:
            if len(records) == 0:
                write_record(name, domain_info, data)
                continue

            for record in records:
                if record.content == domain_info['target_domain'] and not REFRESH_ENTRIES:
                    logger.info("Existing record: %s already points to %s", name, domain_info['target_domain'])
                    continue

                if record_type_change_refused(name, record, data[u'type']):
                    continue

                write_record(name, domain_info, data, record=record)

        except CloudflareAPIError as ex:
            logger.error("** %s - %s", name, ex)
            ok = False

    return ok


def check_container_t1(c):
    def label_host():
        for prop in c.attrs.get(u'Config').get(u'Labels'):
            if re.match('traefik.*.frontend.rule', prop):
                value = c.attrs.get(u'Config').get(u'Labels').get(prop)
                if 'Host' in value:
                    value = value.split("Host:")[1].strip()
                    logger.debug("Container ID:", cont_id, "rule value:", value)
                    if ',' in value:
                        for v in value.split(","):
                            logger.info("Found Container ID: %s with Multi-Hostname %s", cont_id, v)
                            mappings[v] = 1
                    else:
                        logger.info("Found Container ID: %s with Hostname %s", cont_id, value)
                        mappings[value] = 1
                else:
                    pass
    mappings = {}
    logger.debug("Called check_container_t1 for: %s", c)
    cont_id = c.attrs.get(u'Id')
    try:
        TRAEFIK_FILTER
    except NameError:
        label_host()
    else:
        for filter_label in c.attrs.get(u'Config').get(u'Labels'):
            filter_value = c.attrs.get(u'Config').get(u'Labels').get(filter_label)
            if re.match(TRAEFIK_FILTER_LABEL, filter_label) and re.match(TRAEFIK_FILTER, filter_value):
                logger.debug ("Found Container ID: %s with matching label %s with value %s", cont_id, filter_label, filter_value)
                label_host()
    return mappings

    return mappings


def check_service_t1(s):
    def label_host():
        for prop in s.attrs.get(u'Spec').get(u'TaskTemplate').get(u'ContainerSpec').get(u'Labels'):
            if re.match('traefik.*.frontend.rule', prop):
                value = s.attrs.get(u'Spec').get(u'TaskTemplate').get(u'ContainerSpec').get(u'Labels').get(prop)
                if 'Host' in value:
                    value = value.split("Host:")[1].strip()
                    logger.debug("Service ID: %s rule value: %s", cont_id, value)
                    if ',' in value:
                        for v in value.split(","):
                            logger.info("Found Service ID: %s with Multi-Hostname %s", cont_id, v)
                            mappings[v] = 1
                    else:
                        logger.info("Found Service ID: %s with Hostname %s", cont_id, value)
                        mappings[value] = 1
                else:
                    pass
    mappings = {}
    logger.debug("Called check_service_t1 for: %s", s)
    cont_id = s
    s = client.services.get(s)
    try:
        TRAEFIK_FILTER
    except NameError:
        label_host()
    else:
        for filter_label in s.attrs.get(u'Spec').get(u'TaskTemplate').get(u'ContainerSpec').get(u'Labels'):
            filter_value = s.attrs.get(u'Spec').get(u'TaskTemplate').get(u'ContainerSpec').get(u'Labels').get(filter_label)
            if re.match(TRAEFIK_FILTER_LABEL, filter_label) and re.match(TRAEFIK_FILTER, filter_value):
                logger.debug ("Found Service ID %s with matching label %s with value %s", s, filter_label, filter_value)
                label_host()
    return mappings

def check_container_t2(c):
    def label_host():
        for prop in c.attrs.get(u'Config').get(u'Labels'):
            value = c.attrs.get(u'Config').get(u'Labels').get(prop)
            if re.match(r'traefik.*?\.rule', prop):
                if 'Host' in value:
                    logger.debug("Container ID: %s rule value: %s", cont_id, value)
                    extracted_domains = re.findall(r'\`([a-zA-Z0-9\.\-]+)\`', value)
                    logger.debug("Container ID: %s extracted domains from rule: %s", cont_id, extracted_domains)
                    if len(extracted_domains) > 1:
                        for v in extracted_domains:
                            logger.info("Found Service ID: %s with Multi-Hostname %s", cont_id, v)
                            mappings[v] = 1
                    elif len(extracted_domains) == 1:
                        logger.info("Found Service ID: %s with Hostname %s", cont_id, extracted_domains[0])
                        mappings[extracted_domains[0]] = 1
                else:
                    pass
    mappings = {}
    logger.debug("Called check_container_t2 for: %s", c)
    cont_id = c.attrs.get(u'Id')
    try:
        TRAEFIK_FILTER
    except NameError:
        label_host()
    else:
        for filter_label in c.attrs.get(u'Config').get(u'Labels'):
            filter_value = c.attrs.get(u'Config').get(u'Labels').get(filter_label)
            if re.match(TRAEFIK_FILTER_LABEL, filter_label) and re.match(TRAEFIK_FILTER, filter_value):
                logger.debug ("Found Container ID %s with matching label %s with value %s", cont_id, filter_label, filter_value)
                label_host()
    return mappings

def check_service_t2(s):
    def label_host():
        for prop in s.attrs.get(u'Spec').get(u'Labels'):
           value = s.attrs.get(u'Spec').get(u'Labels').get(prop)
           if re.match(r'traefik.*?\.rule', prop):
               if 'Host' in value:
                   logger.debug("Service ID: %s rule value: %s", cont_id, value)
                   extracted_domains = re.findall(r'\`([a-zA-Z0-9\.\-]+)\`', value)
                   logger.debug("Service ID: %s extracted domains from rule: %s", cont_id, extracted_domains)
                   if len(extracted_domains) > 1:
                       for v in extracted_domains:
                           logger.info("Found Service ID: %s with Multi-Hostname %s", cont_id, v)
                           mappings[v] = 1
                   elif len(extracted_domains) == 1:
                       logger.info("Found Service ID: %s with Hostname %s", cont_id, extracted_domains[0])
                       mappings[extracted_domains[0]] = 1
                   else:
                       pass
    mappings = {}
    logger.debug("Called check_service_t2 for: %s", s)
    cont_id = s
    s = client.services.get(s)
    try:
        TRAEFIK_FILTER
    except NameError:
        label_host()
    else:
        for filter_label in s.attrs.get(u'Spec').get(u'Labels'):
            filter_value = s.attrs.get(u'Spec').get(u'Labels').get(filter_label)
            if re.match(TRAEFIK_FILTER_LABEL, filter_label) and re.match(TRAEFIK_FILTER, filter_value):
                logger.debug ("Found Service ID %s with matching label %s with value %s", s, filter_label, filter_value)
                label_host()
    return mappings

def check_traefik(included_hosts, excluded_hosts):
    mappings = {}
    logger.debug("Called check_traefik")
    if TRAEFIK_VERSION == "2":
        r = requests.get("{}/api/http/routers".format(TRAEFIK_POLL_URL))
        if r.ok:
            for router in r.json():
                if "status" in router and router["status"] == "enabled":
                    if "name" in router and "rule" in router:
                        name = router["name"]
                        value = router["rule"]
                        if 'Host' in value:
                            logger.debug("Traefik Router Name: %s rule value: %s", name, value)
                            extracted_domains = re.findall(r'Host\(\`([a-zA-Z0-9\.\-]+)\`\)', value)
                            logger.debug("Traefik Router Name: %s extracted domains from rule: %s", name, extracted_domains)
                            if len(extracted_domains) > 1:
                                for v in extracted_domains:
                                    if is_matching(v, included_hosts):
                                        if is_matching(v, excluded_hosts):
                                            logger.debug("Traefik Router Name: %s with Multi-Hostname %s - Matched Exclude", name, v)
                                        else:
                                            logger.info("Found Traefik Router Name: %s with Multi-Hostname %s", name, v)
                                            mappings[v] = 2
                                    else:
                                        logger.debug("Traefik Router Name: %s with Multi-Hostname %s: Not Match Include", name, v)
                            elif len(extracted_domains) == 1:
                                if is_matching(extracted_domains[0], included_hosts):
                                    if is_matching(extracted_domains[0], excluded_hosts):
                                        logger.debug("Traefik Router Name: %s with Hostname %s - Matched Exclude", name, extracted_domains[0])
                                    else:
                                        logger.info("Found Traefik Router Name: %s with Hostname %s", name, extracted_domains[0])
                                        mappings[extracted_domains[0]] = 2
                                else:
                                    logger.debug("Traefik Router Name: %s with Hostname %s: Not Match Include", name, extracted_domains[0])

    return mappings


def check_traefik_and_sync_mappings(included_hosts, excluded_hosts, domain_infos):
    sync_mappings(check_traefik(included_hosts, excluded_hosts),domain_infos)


def add_to_mappings(current_mappings, mappings):
    for k, v in mappings.items():
        current_mapping = current_mappings.get(k)
        if current_mapping is None or current_mapping > v:
            current_mappings[k] = v


def sync_mappings(mappings, domain_infos):
    for k, v in mappings.items():
        current_mapping = synced_mappings.get(k)
        if current_mapping is None or current_mapping > v:
            if point_domain(k, domain_infos):
                synced_mappings[k] = v


def get_initial_mappings(included_hosts, excluded_hosts):
    logger.debug("Starting Initialization Routines")

    mappings = {}
    if ENABLE_DOCKER_POLL:
        for c in client.containers.list():
            logger.debug("Container List Discovery Loop")
            if TRAEFIK_VERSION == "1":
                add_to_mappings(mappings, check_container_t1(c))
            elif TRAEFIK_VERSION == "2":
                add_to_mappings(mappings, check_container_t2(c))

    if DOCKER_SWARM_MODE:
        logger.debug("Service List Discovery Loop")
        for s in api.services():
            full_serv_id = s["ID"]
            if TRAEFIK_VERSION == "1":
                add_to_mappings(mappings, check_service_t1(full_serv_id))
            elif TRAEFIK_VERSION == "2":
                add_to_mappings(mappings, check_service_t2(full_serv_id))

    if TRAEFIK_POLL_URL:
        logger.debug("Traefik List Discovery Loop")
        add_to_mappings(mappings, check_traefik(included_hosts, excluded_hosts))

    return mappings


def uri_valid(x):
    try:
        result = urlparse(x)
        return all([result.scheme, result.netloc])
    except:
        return False

def get_secret_by_env(envvar_name):
    secret_value:str
    envvar_secret_name=envvar_name + "_FILE"
    envvar_secret_value=os.getenv(envvar_secret_name)
    if envvar_secret_value:
        secret_value = get_docker_secret(envvar_secret_value, secrets_dir='/', autocast_name=False, getenv=False)
    else:
        # fallback check for original environment variable
        secret_value = get_docker_secret(envvar_name, autocast_name=False, getenv=True)
    if secret_value:
        os.environ[envvar_name] = secret_value
        return secret_value

if DRY_RUN.lower() == "true":
    DRY_RUN = True
elif DRY_RUN.lower() == "false":
    DRY_RUN = False

if REFRESH_ENTRIES.lower() == "true":
    REFRESH_ENTRIES = True
elif REFRESH_ENTRIES.lower() == "false":
    REFRESH_ENTRIES = False

if ENABLE_DOCKER_POLL.lower() == "true":
    ENABLE_DOCKER_POLL = True
elif ENABLE_DOCKER_POLL.lower() == "false":
    ENABLE_DOCKER_POLL = False

if DOCKER_SWARM_MODE.lower() == "true":
    DOCKER_SWARM_MODE = True
elif DOCKER_SWARM_MODE.lower() == "false":
    DOCKER_SWARM_MODE = False

if ENABLE_TRAEFIK_POLL.lower() == "true":
    ENABLE_TRAEFIK_POLL = True
elif ENABLE_TRAEFIK_POLL.lower() == "false":
    ENABLE_TRAEFIK_POLL = False

if ALLOW_RECORD_TYPE_CHANGE.lower() == "true":
    ALLOW_RECORD_TYPE_CHANGE = True
elif ALLOW_RECORD_TYPE_CHANGE.lower() == "false":
    ALLOW_RECORD_TYPE_CHANGE = False

if not ENABLE_DOCKER_POLL and DOCKER_SWARM_MODE:
    exit("ERROR: Cannot enable DOCKER_SWARM_MODE without enabling ENABLE_DOCKER_POLL=true")

cf = None
client = None
api = None
email = None
token = None
target_domain = None
domain = None

def load_credentials():
    global email, token, target_domain, domain

    try:
        # Check for uppercase docker secrets or env variables
        email = get_secret_by_env('CF_EMAIL')
        token = get_secret_by_env('CF_TOKEN')

        # Check for any cf zone id based on the respective domain env var existing
        RX_DOMS = re.compile('^DOMAIN[0-9]+$', re.IGNORECASE)
        for env in os.environ:
            if not RX_DOMS.match(env):
                continue

            get_secret_by_env("{}_ZONE_ID".format(env))

        # Check for lowercase docker secrets
        if not email:
            email = get_docker_secret('CF_EMAIL', autocast_name=True, getenv=True)
        if not token:
            token = get_docker_secret('CF_TOKEN', autocast_name=True, getenv=True)

        target_domain = os.environ['TARGET_DOMAIN']
        domain = os.environ['DOMAIN1']

    except KeyError as e:
        exit("ERROR: {} not defined".format(e))


def build_event_filters(swarm_mode=None):
    """Filters for GET /events.

    The daemon's filter keys are lowercase and it silently IGNORES any key it
    does not recognise -- a mis-cased key neither errors nor narrows the
    stream. A standalone daemon never emits type=service either, so filtering
    on it is a watch that can never fire. Service events are added alongside
    container events under Swarm, never in place of them.
    """
    if swarm_mode is None:
        swarm_mode = DOCKER_SWARM_MODE

    types = ['container']
    actions = list(DOCKER_EVENT_CONTAINER_ACTIONS)

    if swarm_mode:
        types.append('service')
        actions.extend(DOCKER_EVENT_SERVICE_ACTIONS)

    return {'type': types, 'event': actions}


def event_type_and_action(event):
    """Read an event's type and action across daemon versions.

    Docker 29 (API 1.55) stopped sending the top-level "status", "id" and
    "from" fields on container events, so dispatching on event['status'] drops
    every event on a current daemon while still looking healthy.
    """
    event_type = event.get(u'Type')
    action = event.get(u'Action') or event.get(u'status')

    if event_type is None and event.get(u'status') is not None:
        event_type = u'container'

    return event_type, action


def event_subject_id(event):
    actor = event.get(u'Actor') or {}
    return actor.get(u'ID') or event.get(u'id')


def handle_event(event, domain_infos, docker_client=None, swarm_mode=None):
    if swarm_mode is None:
        swarm_mode = DOCKER_SWARM_MODE
    if docker_client is None:
        docker_client = client

    event_type, action = event_type_and_action(event)
    subject_id = event_subject_id(event)
    new_mappings = {}

    if event_type == u'container' and action in DOCKER_EVENT_CONTAINER_ACTIONS:
        try:
            container = docker_client.containers.get(subject_id)
        except docker.errors.NotFound:
            # Normal: the container was gone before we could inspect it. Not a
            # reason to stop watching -- doing so silences reconciliation for
            # good on the first race.
            logger.debug("Container %s went away before it could be inspected", subject_id)
            return

        if TRAEFIK_VERSION == "1":
            add_to_mappings(new_mappings, check_container_t1(container))
        elif TRAEFIK_VERSION == "2":
            add_to_mappings(new_mappings, check_container_t2(container))

    elif swarm_mode and event_type == u'service' and action in DOCKER_EVENT_SERVICE_ACTIONS:
        logger.debug("Detected %s on service: %s", action, subject_id)
        try:
            if TRAEFIK_VERSION == "1":
                add_to_mappings(new_mappings, check_service_t1(subject_id))
            elif TRAEFIK_VERSION == "2":
                add_to_mappings(new_mappings, check_service_t2(subject_id))
        except docker.errors.NotFound:
            logger.debug("Service %s went away before it could be inspected", subject_id)
            return

    else:
        return

    if new_mappings:
        sync_mappings(new_mappings, domain_infos)


def watch_events(domain_infos, docker_client=None, swarm_mode=None, since=None, reconnect=True):
    if docker_client is None:
        docker_client = client

    filters = build_event_filters(swarm_mode)
    logger.debug("Docker event filters: %s", filters)

    while True:
        watching_since = since or datetime.now().strftime("%s")
        logger.debug("Watching Docker events since: %s", watching_since)

        for event in docker_client.events(since=watching_since, filters=filters, decode=True):
            handle_event(event, domain_infos, docker_client, swarm_mode)

        if not reconnect:
            return

        logger.debug("Docker event stream ended, resubscribing")
        since = None
        time.sleep(1)


def main():
    global cf, client, api, ENABLE_TRAEFIK_POLL

    load_credentials()

    if DRY_RUN:
        logger.warning("Dry Run: %s", DRY_RUN)
    logger.debug("Docker Polling: %s", ENABLE_DOCKER_POLL)
    logger.debug("Swarm Mode: %s", DOCKER_SWARM_MODE)
    logger.debug("Refresh Entries: %s", REFRESH_ENTRIES)
    logger.debug("Traefik Version: %s", TRAEFIK_VERSION)
    logger.debug("Default TTL: %s", DEFAULT_TTL)

    if not email:
        logger.debug("API Mode: Scoped")
        cf = Cloudflare(api_token=token)
    else:
        logger.debug("API Mode: Global")
        cf = Cloudflare(api_email=email, api_key=token)

    if ENABLE_TRAEFIK_POLL:
        if TRAEFIK_VERSION == "2":
            if uri_valid(TRAEFIK_POLL_URL):
                logger.debug("Traefik Poll Url: %s", TRAEFIK_POLL_URL)
                logger.debug("Traefik Poll Seconds: %s", TRAEFIK_POLL_SECONDS)
            else:
                ENABLE_TRAEFIK_POLL = False
                logger.error("Traefik Polling Mode disabled because traefik url is invalid: %s", TRAEFIK_POLL_URL)
        else:
            ENABLE_TRAEFIK_POLL = False
            logger.error("Traefik Polling Mode disabled because traefik version is not 2")

    logger.debug("Traefik Polling Mode: %s", ENABLE_TRAEFIK_POLL)

    if ENABLE_DOCKER_POLL:
        client = docker.from_env()

        if DOCKER_SWARM_MODE:
            DOCKER_HOST = os.environ.get('DOCKER_HOST', None)
            api = docker.APIClient(base_url=DOCKER_HOST)

    doms = init_doms_from_env()
    traefik_included_hosts, traefik_excluded_hosts = init_traefik_from_env()

    sync_mappings(get_initial_mappings(traefik_included_hosts, traefik_excluded_hosts), doms)

    if ENABLE_TRAEFIK_POLL:
        logger.debug("Starting traefik router polling")
        traefik_poll = RepeatedTimer(TRAEFIK_POLL_SECONDS, check_traefik_and_sync_mappings, args=(traefik_included_hosts, traefik_excluded_hosts, doms))
        traefik_poll.start()
        atexit.register(traefik_poll.cancel)

    logger.debug("Starting event watch routines")

    if ENABLE_DOCKER_POLL:
        watch_events(doms)


if __name__ == '__main__':
    main()
