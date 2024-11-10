# FindMy2MQTT

A small python script to periodically fetch location data from Apple's FindMy network and publish it to an mqtt server. This is just a tiny wrapper around the FindMy.py project. You need a working Apple account and some tracker credentials to use it. You can use `.plist` files extracted from your Mac or Mac VM for genuine Apple devices or `.json` files for DIY trackers like they are used with Macless-Haystack.

## How to run

You need to run interactively at first to login with 2FA:
```
docker-compose up -d
docker-compose run --rm findmy2mqtt
docker-compose up -d
```

Example docker-compose configuration:
```
version: '3'

volumes:
  anisette-config:
  anisette-provisioning:

services:
  anisette:
    image: dadoum/anisette-v3-server
    container_name: anisette
    restart: always
    ports:
      - 6969:6969
    volumes:
      - anisette-config:/home/Alcoholic/.config/anisette-v3/
      - anisette-provisioning:/opt/provisioning
  mqtt:
    image: eclipse-mosquitto:2.0.13
    restart: always
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data
      - ./mosquitto/log:/mosquitto/log
    ports:
      - 1883:1883
      - 9001:9001

  findmy2mqtt:
    image: maz3max/findmy2mqtt:0.1.0
    environment:
      - MQTT_HOST="mqtt://mqtt"
      - MQTT_PORT=1883
      - MQTT_USERNAME=test
      - MQTT_PASSWORD=very-secure-password
      - MQTT_TOPIC=findmy
      - ANISETTE_SERVER=http://0.0.0.0:6969
      - FETCH_INTERVAL_MINUTES=1
      - ACCOUNT_STORE=/app/config/account.json
      - AIRTAG_FOLDER=/app/config/tags
    depends_on:
      - mqtt
      - anisette
    volumes:
      - ./findmy2mqtt:/app/config/
    network_mode: "host"
```

## Controlling when to fetch

You can set the fetch interval with the `FETCH_INTERVAL_MINUTES` env variable. Also, sending any MQTT message to `findmy/get` will trigger a location data fetch.

## Adding new tags

Rename the `.plist` files before copying to human readible names and copy them into your tags folder. Restart the service to load new tags.
