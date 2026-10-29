up:
	docker-compose up

down:
	docker-compose down

build:
	docker-compose up --build

makemigrations:
	docker-compose run --rm app sh -c "python manage.py makemigrations"

migrate:
	docker-compose run --rm app sh -c "python manage.py wait_for_db && python manage.py migrate"

loaddata:
	docker-compose run --rm app sh -c "python manage.py loaddata db.json --exclude=contenttypes --exclude=auth.permission"

test:
	docker-compose run --rm app sh -c "python manage.py test --settings=config.settings.test"

shell:
	docker-compose run --rm app sh -c "python manage.py shell"

createsuperuser:
	docker-compose run --rm app sh -c "python manage.py createsuperuser"

startapp:
	docker-compose run --rm app sh -c "python manage.py startapp $(filter-out $@,$(MAKECMDGOALS))"

testapp:
	docker-compose run --rm app sh -c "python manage.py test $(filter-out $@,$(MAKECMDGOALS)) --settings=config.settings.test"

testfile:
	docker-compose run --rm app sh -c "python manage.py test $(word 2,$(MAKECMDGOALS)).tests.$(word 3,$(MAKECMDGOALS)) --settings=config.settings.test"

testfunc:
	docker-compose run --rm app sh -c "python manage.py test $(word 2,$(MAKECMDGOALS)).tests.$(word 3,$(MAKECMDGOALS)).$(word 4,$(MAKECMDGOALS)).$(word 5,$(MAKECMDGOALS)) --settings=config.settings.test"

testws:
	docker-compose run --rm app sh -c "python manage.py test notification.tests.test_new_notification_ws notification.tests.test_sockets activity_badge.tests.test_websocket --settings=config.settings.test"

run:
	docker-compose run --rm app sh -c "python manage.py $(filter-out $@,$(MAKECMDGOALS))"

# 해당 목표가 실제로 존재하지 않음을 Make에 알려주는 더미 규칙
%:
	@: