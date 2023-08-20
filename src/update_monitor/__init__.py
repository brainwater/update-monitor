#!/usr/bin/env python3
# coding=utf-8

# Depends on apt package update-notifier-common (for '/usr/lib/update-notifier/apt-check') and apt packeage python3-paho-mqtt

import os
import platform
import sys
import subprocess
import json
import socket
import time
import gettext
from optparse import OptionParser
import paho.mqtt.client as mqtt

UPDATE_DELAY = 60*30

secrets_path = "/etc/homeassistant/secrets.json"
directory = os.path.dirname(__file__)
second_secrets_path = os.path.join(directory, "secrets.json")
secrets = None
for path in [secrets_path, second_secrets_path]:
    if os.path.isfile(path):
        with open(path) as sfile:
            secrets = json.load(sfile)
        break
if secrets is None:
    raise SystemExit("Error! No file found at " + secrets_path + " or " + second_secrets_path + " unable to send!")

def numWindowsUpdate():
    powershell = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    runresult = subprocess.run([powershell, "Get-WindowsUpdate", "-AutoSelectOnWebSites"], capture_output=True)
    if runresult.returncode != 0:
        print("Error with stuff")
        print(runresult.stdout.decode("utf-8"))
        print("Stderr:")
        print(runresult.stderr.decode("utf-8"))
        out = None
        runresult.check_returncode()
    else:
        out = runresult.stdout
    lines = out.split("\r\n".encode("ascii"))
    print(lines)
    numupdates = len(lines) - 6
    print(numupdates)
    if numupdates < 0:
        numupdates = 0
    return numupdates

def init_mqtt_client(username, password, broker, port):
    mqtt_client = mqtt.Client(socket.gethostname())
    mqtt_client.username_pw_set(username, password=password)
    mqtt_client.connect(broker, port)
    return mqtt_client

def getTopic(sensorType, postfix="/state", prefix=socket.gethostname()):
    return "homeassistant/binary_sensor/" + prefix + sensorType + postfix
    

def advertise(mqtt_client):
    topic = getTopic("update", "/config")
    payload = {
        "name": socket.gethostname() + " Updates Available",
        "device_class": "update",
        "state_topic": getTopic("update"),
        "expire_after": UPDATE_DELAY * 3,
        "unique_id": socket.gethostname() + "update",
        "value_template": "{{ value_json.state }}"
    }
    pub(mqtt_client, topic, json.dumps(payload))
    print("Advertised")

def sendvalue(mqtt_client, num_updates: int):
    val = "OFF"
    if num_updates > 0:
        val = "ON"
    payload = {"state": val}
    topic = getTopic("update")
    pub(mqtt_client, topic, json.dumps(payload))
    print("Sent value")

def pub(mqtt_client, topic, output):
    retval = mqtt_client.publish(topic, output, qos=1)
    if retval.rc == mqtt.MQTT_ERR_NO_CONN:
        # TODO: Better handle and log errors
        print("Error, no connection!")
        mqtt_client.reconnect()
    if retval.rc != mqtt.MQTT_ERR_SUCCESS:
        print("Unknown error when publishing value!")

def _(msg):
    return gettext.dgettext("update-notifier", msg)

def isNixOS():
    if not os.path.exists("/etc/lsb-release"):
        return False
    with open("/etc/lsb-release", "rb") as lsbfile:
        lines = [line for line in lsbfile.readlines() if len(line) > 2 and line.startswith(b"DISTRIB_ID")]
        if len(lines) < 1:
            return False
        items = lines[0].split(b"=")
        if len(items) < 2:
            return False
        if b"nixos" in items[1]:
            return True
    return False

def isWindows():
    return platform.system() == "Windows"

if __name__ == "__main__":
    time.sleep(5)
    #dir_path = os.path.dirname(os.path.realpath(__file__))
    #blarg_path = os.path.join(dir_path, "blarg.py")
    #try:
    #    apt_check_output = subprocess.check_output(blarg_path, stderr=subprocess.STDOUT).decode('utf-8')
    #    output_lst = apt_check_output.split(";")
    #    num_updates, num_security = int(output_lst[0]), output_lst[1]
    parser = OptionParser()
    parser.add_option("-p",
                      "--package-names",
                      action="store_true",
                      dest="show_package_names",
                      help=_("Show the packages that are "
                             "going to be installed/upgraded"))
    parser.add_option("",
                      "--human-readable",
                      action="store_true",
                      dest="readable_output",
                      help=_("Show human readable output on stdout"))
    parser.add_option("",
                      "--security-updates-unattended",
                      action="store_true",
                      help=_("Return the time in days when security updates "
                             "are installed unattended (0 means disabled)"))
    (options, args) = parser.parse_args()
    if isNixOS():
        # May need root permission!
        nix_output = subprocess.check_output(['nixos-rebuild', 'dry-run', '--upgrade'], stderr=subprocess.STDOUT).decode('utf-8')
        num_updates = len(nix_output.split("\n")) - 3
        if num_updates < 0:
            print("Error, got negative number of updates for nixos")
            num_updates = 0
    elif isWindows():
        num_updates = numWindowsUpdate()
    else:
        import debian_update_check
        debian_update_check.init()
        num_updates, num_security_updates = debian_update_check.run(options)
        #print(num_updates)
    #print("Num updates: " + str(num_updates))
    #print("Num security: " + str(num_security))

    mqtt_client = init_mqtt_client(
        username=secrets['mqtt_username'],
        password=secrets['mqtt_password'],
        broker=secrets['mqtt_broker'],
        port=secrets['mqtt_port'])

    advertise(mqtt_client)
    sendvalue(mqtt_client, num_updates)
    time.sleep(5)
