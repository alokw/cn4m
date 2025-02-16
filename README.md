# outbox_cn4m
 
add assets to the repo
run a check
assets discovered for the first time are added to unreviewed_assets
if they are approved, they are moved to untracked_repo_assets
if they are quarantined, they are moved to untracked_quar_assets
when they are tracked (sent to google) they are moved to tracked...assets


cd /Users/outbox/Documents/GitHub/outbox_cn4m
docker compose up (run in foreground)
docker-compose up -d (run in background)

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





