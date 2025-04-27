# cn4m

### about
cn4m was developed by creative outbox to help establish a consistent content management and tracking ecosystem
 
### general workflow
 1. add assets to the repo
 2. run a check
 3. assets discovered for the first time are added to unreviewed_assets
 4. if they are approved, they are moved to untracked_repo_assets
 5. if they are quarantined, they are moved to untracked_quar_assets
 6. when they are tracked (sent to google) they are moved to tracked...assets

### how to install cn4m server
 1. install git or github desktop
 2. clone the cn4m repository
    > in github desktop -> file -> clone repository -> https://github.com/alokw/outbox_cn4m.git
 3. modify the .env file with your preferences and info

### how to run cn4m server
 1. make sure docker engine is running
 2. in powershell (windows) or terminal (mac), navigate to the cn4m directory
    > (windows) cd D:\github\outbox_cn4m
    > (mac) cd /Users/outbox/Documents/GitHub/outbox_cn4m
 3. run docker compose
    > (in foreground) docker compose up
    > (in background) docker compose up -d


to-do
add conversion buttons and aerender buttons
update push to google to include flagged assets
add nickname for hvc1 codec




if running in background, manually check logs with
docker-compose logs

to show running containers
docker ps

to show specific logs
docker-compose logs -f web  # Replace 'web' with your service name


to rebuild & restart the container
docker-compose up --build


to rebuild containers (to refresh requirements)
docker-compose down --remove-orphans
docker-compose build --no-cache
docker-compose up



docker ps   #show all running containers
docker exec -it <container_name> sh   # run a command in a container






to force rebuild the image with fresh dependencies (need to do if adding requirements)
docker-compose build --no-cache
then restart the containers
docker-compose up -d

alternatively if you dont want to rebuild everythong...
docker exec -it flask_app sh  # Open a shell inside the Flask container
pip install -r requirements.txt  # Manually install new dependencies
exit  # Exit the container
docker-compose down  # Stop running containers
docker-compose up --build -d  # Rebuild with new dependencies









notes for later:
consider running multiple Celery workers
docker-compose up --scale worker=3 -d





## Troubleshooting:

 - If you get a "*connect ENOENT \.\pipe\errorReporter*" error from docker
   at startup, add yourself to the docker users group by running the
   following in PowerShell (as administrator):
	> net localgroup docker-users <<your windows username>> /add
