# periodically fetch FindMy location reports and publish them to MQTT

import json
import logging
from pathlib import Path
import os
import json
import threading

from findmy import FindMyAccessory
from findmy.reports import (
    AppleAccount,
    RemoteAnisetteProvider,
    BaseAnisetteProvider,
    LoginState,
    SmsSecondFactorMethod,
    TrustedDeviceSecondFactorMethod,
)
from findmy import KeyPair

import paho.mqtt.client as mqtt

ACCOUNT_STORE = os.getenv("ACCOUNT_STORE", "account.json")
AIRTAG_FOLDER = os.getenv("AIRTAG_FOLDER", "tags")

MQTT_SERVER = os.getenv("MQTT_SERVER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "test")
MQTT_PASS = os.getenv("MQTT_PASS", "very-secure-password")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "findmy")

ANISETTE_SERVER = os.getenv("ANISETTE_SERVER", "http://localhost:6969")

FETCH_INTERVAL_MINUTES = int(os.getenv("FETCH_INTERVAL_MINUTES", "1"))

HOURS_TO_FETCH = (FETCH_INTERVAL_MINUTES // 60) + 1

message_received_event = threading.Event()

logging.basicConfig(level=logging.INFO)

has_mqtt = False

def _apple_login_sync(account: AppleAccount) -> None:
    email = input("email?  > ")
    password = input("passwd? > ")

    state = account.login(email, password)

    if state == LoginState.REQUIRE_2FA:  # Account requires 2FA
        # This only supports SMS methods for now
        methods = account.get_2fa_methods()

        # print the (masked) phone numbers
        for i, method in enumerate(methods):
            if isinstance(method, TrustedDeviceSecondFactorMethod):
                print(f"{i} - Trusted Device")
            elif isinstance(method, SmsSecondFactorMethod):
                print(f"{i} - SMS ({method.phone_number})")

        ind = int(input("Method? > "))

        method = methods[ind]
        method.request()
        code = input("Code? > ")

        # This automatically finishes the post-2FA login flow
        method.submit(code)

def get_apple_account_sync(anisette: BaseAnisetteProvider) -> AppleAccount:
    """Tries to restore a saved Apple account, or prompts the user for login otherwise. (sync)"""
    acc = AppleAccount(anisette)

    # Save / restore account logic
    acc_store = Path(ACCOUNT_STORE)
    try:
        with acc_store.open() as f:
            acc.restore(json.load(f))
    except FileNotFoundError:
        _apple_login_sync(acc)
        with acc_store.open("w+") as f:
            json.dump(acc.export(), f)

    return acc

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, reason_code, properties):
    global has_mqtt
    if reason_code == 0:
        has_mqtt = True
        logging.info(f"Successfully connected to MQTT server")
        client.subscribe(f"{MQTT_TOPIC}/get")
    else:
        logging.error(f"Failed to connect to MQTT server, reason code {reason_code}")
        has_mqtt = False

def on_disconnect(*args):
    global has_mqtt
    logging.error(f"Disconnected from MQTT server")
    has_mqtt = False

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    logging.info(msg.topic+" "+str(msg.payload))
    message_received_event.set()

positions = []
positions_lock = threading.Lock()

def update_positions(report, name):
    global positions

    ts = str(report.timestamp)
    with positions_lock:
        for p in positions:
            if p["name"] == name:
                if ts > p["ts"]:
                    p["lat"] = report.latitude
                    p["lon"] = report.longitude
                    p["ts"] = ts
                return
        positions.append({"id": len(positions) + 1, "lat": report.latitude, "lon": report.longitude, "name": name, "ts": ts})


def fetcher_thread():
    airtags = []
    airtag_names = []
    for file in os.listdir(AIRTAG_FOLDER):
        if file.endswith(".plist"):
            with open(os.path.join(AIRTAG_FOLDER, file), "rb") as f:
                airtags.append(FindMyAccessory.from_plist(f))
                airtag_names.append(file[:-6])
        if file.endswith(".json"):
            json_data = json.load(open(os.path.join(AIRTAG_FOLDER, file)))
            for entry in json_data:
                airtags.append(KeyPair.from_b64(entry["privateKey"]))
                airtag_names.append(entry["name"])
                for key in entry["additionalKeys"]:
                    airtags.append(KeyPair.from_b64(key))
                    airtag_names.append(entry["name"])

    reports = [[]] * len(airtags)
    reports_to_publish = [[]] * len(airtags)

    logging.info("Logging into Apple account")
    anisette = RemoteAnisetteProvider(ANISETTE_SERVER)
    acc = get_apple_account_sync(anisette)

    logging.info("Connecting to MQTT server")
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_message = on_message

    mqttc.username_pw_set(MQTT_USER, MQTT_PASS)
    mqttc.connect(MQTT_SERVER, MQTT_PORT, 60)

    mqttc.loop_start()

    while True:
        if has_mqtt:
            logging.info("Fetching reports")
            try:
                for i, airtag in enumerate(airtags):
                    old_reports = reports[i]
                    new_reports = acc.fetch_last_reports(airtag, hours=HOURS_TO_FETCH)
                    reports[i] = new_reports
                    reports_to_publish[i] = [r for r in new_reports if r not in old_reports]
            except Exception as e:
                logging.error(f"Error fetching reports: {e}")

            logging.info("Publishing reports")
            for i, airtag in enumerate(airtags):
                logging.info(f"Publishing {len(reports_to_publish[i])} reports for {airtag_names[i]}")
                for report in reports_to_publish[i]:
                    report_obj = {
                            "lat" : report.latitude,
                            "lon" : report.longitude,
                            "ts" : str(report.timestamp),
                            "acc" : report.confidence,
                        }
                    report_str = json.dumps(report_obj)
                    mqttc.publish(f"{MQTT_TOPIC}/dev/{airtag_names[i]}", report_str)
                    update_positions(report, airtag_names[i])

        # Wait for the event with a timeout
        logging.info(f"Waiting for {FETCH_INTERVAL_MINUTES} minutes")
        message_received_event.wait(FETCH_INTERVAL_MINUTES * 60)
        message_received_event.clear()

    mqttc.loop_stop()

from flask import Flask, render_template, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("map.html")

@app.route("/positions")
def get_positions():
    message_received_event.set()
    with positions_lock:
        positions_without_ts = [{"id": p["id"], "lat": p["lat"], "lon": p["lon"], "name": p["name"]} for p in positions]
        return jsonify(positions_without_ts)

if __name__ == "__main__":
    threading.Thread(target=fetcher_thread).start()
    app.run(port=5105, host='0.0.0.0')
