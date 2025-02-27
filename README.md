# fieldcam
Streaming Cam Setup For Ball Fields

build.sh
 will create the camapp docker image

d-up.sh
 will start docker container

crontab

you need a cron job to take field snapshots

something like this
```cron
* * * * * /usr/bin/ffmpeg -hide_banner -loglevel error -y -i rtsp://USERNAME:PASSWORD@IPADDRESS:554/Streaming/channels/102/ -frames:v 1 -q:v 2 /home/stream411/fieldcam/cam-app/app/static/field.jpg
```

FIXME: Make this a docker container job?

