#SPDX-License-Identifier: MIT
from conftest import augur_app
from os import walk, chdir, environ, chmod, path
import os
import logging
from sys import exit
import stat
from collections import OrderedDict
from subprocess import call
import random
import string
import csv
import click
import sqlalchemy as s
import pandas as pd
import requests
import json
from sqlalchemy import exc

from augur.cli import pass_config, pass_application
from augur.platform_connector import PlatformConnector

logger = logging.getLogger(__name__)

@click.group('db', short_help='Database utilities')
def cli():
    pass

@cli.command('add-repos')
@click.argument('filename', type=click.Path(exists=True))
@pass_application
def add_repos(augur_app, filename):
    """
    Add repositories to Augur's database
    """
    df = augur_app.database.execute(s.sql.text("SELECT repo_group_id FROM augur_data.repo_groups"))
    repo_group_IDs = [group[0] for group in df.fetchall()]

    insertSQL = s.sql.text("""
        INSERT INTO augur_data.repo(repo_group_id, repo_git, repo_status,
        tool_source, tool_version, data_source, data_collection_date)
        VALUES (:repo_group_id, :repo_git, 'New', 'CLI', 1.0, 'Git', CURRENT_TIMESTAMP)
    """)

    with open(filename) as upload_repos_file:
        data = csv.reader(upload_repos_file, delimiter=',')
        for row in data:
            logger.info(f"Inserting repo with Git URL `{row[1]}` into repo group {row[0]}")
            if int(row[0]) in repo_group_IDs:
                result = augur_app.database.execute(insertSQL, repo_group_id=int(row[0]), repo_git=row[1])
            else:
                logger.warning(f"Invalid repo group id specified for {row[1]}, skipping.")

@cli.command('get-repo-groups')
@pass_application
def get_repo_groups(augur_app):
    """
    List all repo groups and their associated IDs
    """
    df = pd.read_sql(s.sql.text("SELECT repo_group_id, rg_name, rg_description FROM augur_data.repo_groups"), augur_app.database)
    print(df)

    return df

@cli.command('add-repo-groups')
@click.argument('filename', type=click.Path(exists=True))
@pass_application
def add_repo_groups(augur_app, filename):
    """
    Create new repo groups in Augur's database
    """
    df = pd.read_sql(s.sql.text("SELECT repo_group_id FROM augur_data.repo_groups"), augur_app.database)
    repo_group_IDs = df['repo_group_id'].values.tolist()

    insert_repo_group_sql = s.sql.text("""
    INSERT INTO "augur_data"."repo_groups"("repo_group_id", "rg_name", "rg_description", "rg_website", "rg_recache", "rg_last_modified", "rg_type", "tool_source", "tool_version", "data_source", "data_collection_date") VALUES (:repo_group_id, :repo_group_name, '', '', 0, CURRENT_TIMESTAMP, 'Unknown', 'Loaded by user', '1.0', 'Git', CURRENT_TIMESTAMP);
    """)

    with open(filename) as create_repo_groups_file:
        data = csv.reader(create_repo_groups_file, delimiter=',')
        for row in data:
            logger.info(f"Inserting repo group with name {row[1]} and ID {row[0]}...")
            if int(row[0]) not in repo_group_IDs:
                repo_group_IDs.append(int(row[0]))
                augur_app.database.execute(insert_repo_group_sql, repo_group_id=int(row[0]), repo_group_name=row[1])
            else:
                logger.info(f"Repo group with ID {row[1]} for repo group {row[1]} already exists, skipping...")

@cli.command('add-github-org')
@click.argument('organization_name')
@pass_application
def add_github_org(augur_app, organization_name):
    """
    Create new repo groups in Augur's database
    """
    org_query_response = requests.get(f"https://api.github.com/orgs/{organization_name}").json()
    if "login" in org_query_response:
        logger.info(f"Organization \"{organization_name}\" found")
    else:
        logger.fatal(f"No organization with name {organization_name} could be found")
        exit(1)

    all_repos = []
    page = 1
    repo_query_response = None
    headers = {'Authorization': 'token %s' % augur_app.config.get_value("Database", "key")}
    while repo_query_response != []:
        repo_query_response = requests.get(org_query_response['repos_url'] + f"?per_page=100&page={page}", headers=headers).json()
        for repo in repo_query_response:
            all_repos.append(repo)
        page+=1

    insert_repo_group_sql = s.sql.text("""
    INSERT INTO "augur_data"."repo_groups"("rg_name", "rg_description", "rg_website", "rg_recache", "rg_last_modified", "rg_type", "tool_source", "tool_version", "data_source", "data_collection_date") VALUES (:repo_group_name, '', '', 0, CURRENT_TIMESTAMP, 'Unknown', 'Loaded by user', '1.0', 'Git', CURRENT_TIMESTAMP) RETURNING repo_group_id;
    """)
    new_repo_group_id = augur_app.database.execute(insert_repo_group_sql, repo_group_name=organization_name).fetchone()[0]

    insert_repo_sql = s.sql.text("""
        INSERT INTO augur_data.repo(repo_group_id, repo_git, repo_status,
        tool_source, tool_version, data_source, data_collection_date)
        VALUES (:repo_group_id, :repo_git, 'New', 'CLI', 1.0, 'Git', CURRENT_TIMESTAMP)
    """)
    logger.info(f"{organization_name} repo group created")

    for repo in all_repos:
        logger.info(f"Adding {organization_name}/{repo['name']} ({repo['clone_url']})")
        result = augur_app.database.execute(insert_repo_sql, repo_group_id=new_repo_group_id, repo_git=repo['clone_url'])

# get_db_version is a helper function to print_db_version and upgrade_db_version
def get_db_version(augur_app):
    db_version_sql = s.sql.text("""
        SELECT * FROM augur_operations.augur_settings WHERE setting = 'augur_data_version'
    """)

    return int(augur_app.database.execute(db_version_sql).fetchone()[2])

@cli.command('print-db-version')
@pass_application
def print_db_version(augur_app):
    """
    Get the version of the configured database
    """
    print(get_db_version(augur_app))

@cli.command('upgrade-db-version')
@pass_application
def upgrade_db_version(augur_app):
    """
    Upgrade the configured database to the latest version
    """
    check_pgpass_credentials(augur_app.config.get_raw_config())
    current_db_version = get_db_version(augur_app)

    update_scripts_filenames = []
    for (_, _, filenames) in walk('schema/generate'):
        update_scripts_filenames.extend([file for file in filenames if 'update' in file])
        # files_temp.extend([file.split("-")[1][14:].split(".")[0] for file in filenames if 'update' in file])
        break

    target_version_script_map = {}
    for script in update_scripts_filenames:
        upgrades_to = int(script.split("-")[1][14:].split(".")[0])
        target_version_script_map[upgrades_to] = str(script)

    target_version_script_map = OrderedDict(sorted(target_version_script_map.items()))

    most_recent_version = list(target_version_script_map.keys())[-1]
    if current_db_version == most_recent_version:
        logger.info("Your database is already up to date. ")
    elif current_db_version > most_recent_version:
        logger.error(f"Unrecognized version: {current_db_version}\nThe most recent version is {most_recent_version}. Please contact your system administrator to resolve this error.")

    for target_version, script_location in target_version_script_map.items():
        if target_version == current_db_version + 1:
            logger.info(f"Upgrading from {current_db_version} to {target_version}")
            run_psql_command_in_database(augur_app, '-f', f"schema/generate/{script_location}")
            current_db_version += 1

@cli.command('check-for-upgrade')
@pass_application
def check_for_upgrade(augur_app):
    """
    Upgrade the configured database to the latest version
    """
    check_pgpass_credentials(augur_app.config.get_raw_config())
    current_db_version = get_db_version(augur_app)

    update_scripts_filenames = []
    for (_, _, filenames) in walk('schema/generate'):
        update_scripts_filenames.extend([file for file in filenames if 'update' in file])
        # files_temp.extend([file.split("-")[1][14:].split(".")[0] for file in filenames if 'update' in file])
        break

    target_version_script_map = {}
    for script in update_scripts_filenames:
        upgrades_to = int(script.split("-")[1][14:].split(".")[0])
        target_version_script_map[upgrades_to] = str(script)

    target_version_script_map = OrderedDict(sorted(target_version_script_map.items()))

    most_recent_version = list(target_version_script_map.keys())[-1]
    if current_db_version == most_recent_version:
        logger.info("Database is already up to date.")
    elif current_db_version < most_recent_version:
        logger.info(f"Current database version: v{current_db_version}\nPlease upgrade to the most recent version (v{most_recent_version}) with augur db upgrade-db-version.")
    elif current_db_version > most_recent_version:
        logger.error(f"Unrecognized version: {current_db_version}\nThe most recent version is {most_recent_version}. Please contact your system administrator to resolve this error.")


@cli.command('create-schema')
@pass_application
def create_schema(augur_app):
    """
    Create schema in the configured database
    """
    check_pgpass_credentials(augur_app.config.get_raw_config())
    run_psql_command_in_database(augur_app, '-f', 'schema/create_schema.sql')

def generate_key(length):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

@cli.command('generate-api-key')
@click.pass_context
def generate_api_key(ctx):
    """
    Generate and set a new Augur API key
    """
    key = generate_key(32)
    ctx.invoke(update_api_key, api_key=key)
    print(key)

@cli.command('update-api-key')
@click.argument("api_key")
@pass_application
def update_api_key(augur_app, api_key):
    """
    Update the API key in the database to the given key
    """
    update_api_key_sql = s.sql.text("""
        UPDATE augur_operations.augur_settings SET VALUE = :api_key WHERE setting='augur_api_key';
    """)

    augur_app.database.execute(update_api_key_sql, api_key=api_key)
    logger.info(f"Updated Augur API key to: {api_key}")

@cli.command('get-api-key')
@pass_application
def get_api_key(augur_app):
    get_api_key_sql = s.sql.text("""
        SELECT value FROM augur_operations.augur_settings WHERE setting='augur_api_key';
    """)

    try:
        print(augur_app.database.execute(get_api_key_sql).fetchone()[0])
    except TypeError:
        logger.error("No Augur API key found.")

@cli.command('check-pgpass', short_help="Check the ~/.pgpass file for Augur's database credentials")
@pass_config
def check_pgpass(config):
    check_pgpass_credentials(config.get_raw_config())

@cli.command('init-database')
@click.option('--default-db-name', default='postgres')
@click.option('--default-user', default='postgres')
@click.option('--default-password', default='postgres')
@click.option('--target-db-name', default='augur')
@click.option('--target-user', default='augur')
@click.option('--target-password', default='augur')
@click.option('--host', default='localhost')
@click.option('--port', default='5432')
def init_database(default_db_name, default_user, default_password, target_db_name, target_user, target_password, host, port):
    """
    Create database with the given credentials using the given maintenance database
    """
    config = {
        'Database': {
            'name': default_db_name,
            'user': default_user,
            'password': default_password,
            'host': host,
            'port': port
        }
    }
    check_pgpass_credentials(config)
    run_db_creation_psql_command(host, port, default_user, default_db_name, f'CREATE DATABASE {target_db_name};')
    run_db_creation_psql_command(host, port, default_user, default_db_name, f'CREATE USER {target_user} WITH ENCRYPTED PASSWORD \'{target_password}\';')
    run_db_creation_psql_command(host, port, default_user, default_db_name, f'ALTER DATABASE {target_db_name} OWNER TO {target_user};')
    run_db_creation_psql_command(host, port, default_user, default_db_name, f'GRANT ALL PRIVILEGES ON DATABASE {target_db_name} TO {target_user};')

def run_db_creation_psql_command(host, port, user, name, command):
    call(['psql', '-h', host, '-p', port, '-U', user, '-d', name, '-a', '-w', '-c', command])

def run_psql_command_in_database(augur_app, target_type, target):
    if target_type not in ['-f', '-c']:
        logger.error("Invalid target type. Exiting...")
        exit(1)

    call(['psql', '-h', augur_app.config.get_value('Database', 'host'),\
      '-d', augur_app.config.get_value('Database', 'name'),\
      '-U', augur_app.config.get_value('Database', 'user'),\
      '-p', str(augur_app.config.get_value('Database', 'port')),\
      '-a', '-w', target_type, target
    ])

def check_pgpass_credentials(config):
    pgpass_file_path = environ['HOME'] + '/.pgpass'

    if not path.isfile(pgpass_file_path):
        logger.info("~/.pgpass does not exist, creating.")
        open(pgpass_file_path, 'w+')
        chmod(pgpass_file_path, stat.S_IWRITE | stat.S_IREAD)

    pgpass_file_mask = oct(os.stat(pgpass_file_path).st_mode & 0o777)

    if pgpass_file_mask != '0o600':
        logger.info("Updating ~/.pgpass file permissions.")
        chmod(pgpass_file_path, stat.S_IWRITE | stat.S_IREAD)

    with open(pgpass_file_path, 'a+') as pgpass_file:
        end = pgpass_file.tell()
        pgpass_file.seek(0)

        credentials_string = str(config['Database']['host']) \
                          + ':' + str(config['Database']['port']) \
                          + ':' + str(config['Database']['name']) \
                          + ':' + str(config['Database']['user']) \
                          + ':' + str(config['Database']['password'])

        if credentials_string.lower() not in [''.join(line.split()).lower() for line in pgpass_file.readlines()]:
            logger.info("Adding credentials to $HOME/.pgpass")
            pgpass_file.seek(end)
            pgpass_file.write(credentials_string + '\n')
        else:
            logger.info("Credentials found in $HOME/.pgpass")

@cli.command('update-org-repositories')
@click.argument('org')
@pass_application
def update_org_repositories(augur_app, org):
    """
    Add new repositories for specific organization to Augur's database
    """

    nonArchivedTotalCount = get_non_archived_repos_total_count(augur_app, org)
    repo_group_id = get_org_id(augur_app, org)
    existing_repos = get_existing_repos(augur_app, repo_group_id)

    if nonArchivedTotalCount > len(existing_repos):
        repos = get_all_non_archived_repos(augur_app, org, nonArchivedTotalCount)

        for repo in repos:
            if repo['node']['name'] not in existing_repos:
                insert_repo(augur_app, repo['node'], org, repo_group_id)

def insert_repo(augur_app, repo, org, repo_group_id):
    logger.info("Inserting repo {}".repo['name'])
    insert_repo_sql = s.sql.text("""
        INSERT INTO augur_data.repo(repo_group_id, repo_git, repo_path, repo_name, repo_added)
        VALUES ({}, {}, {}, {}, {})
    """.format(repo_group_id, '\''+repo['url']+'\'', '\'github.com/'+org+'/\'', '\''+repo['name']+'\'', '\''+repo['createdAt']+'\''))

    augur_app.database.execute(insert_repo_sql)
    return

def get_value_from_fetch_data(data):
    return data[0]

def get_existing_repos(augur_app, repo_group_id):
    repos_sql = s.sql.text("""
            SELECT repo_name FROM repo
            WHERE repo_group_id = '{}' AND repo_archived = 0
        """.format(repo_group_id))

    repos = augur_app.database.execute(repos_sql).fetchall()

    if len(repos) == 0:
        logger.info("Did not find any repositories stored in augur_database for repo_group_id {}\n".format(repo_group_id))

    repos_list = list(map(get_value_from_fetch_data, repos))

    return repos_list

def get_org_id(augur_app, org):
    org_id_sql = s.sql.text("""
            SELECT repo_group_id FROM repo_groups
            WHERE rg_name = '{}'
        """.format(org))

    org_id = augur_app.database.execute(org_id_sql).fetchone()[0]
    if type(org_id) != int:
        logger.info("Failed to get organization id from org {}".format(org))
    return org_id

def get_all_non_archived_repos(augur_app, org, totalCount):
    maxCount = 100
    nodes = []
    after = ""

    while totalCount > maxCount or totalCount <= maxCount and totalCount > 0:
        totalCount = totalCount - maxCount
        query = """
        {
            repos: search(query: "user:%s archived:false", type: REPOSITORY, first:  %d%s) {
                edges {
                    node {
       					... on Repository {
                            id
                            name
                            nameWithOwner
                            url
                            createdAt
                        }
                    }
                    cursor
                }
            }
        }
        """ % (org, maxCount, after)

        data = get_data(augur_app, query, org)
        if 'data' not in data:
            logger.info("Could not get a list of all repositories. 'data' is missing in: {}\n".format(data))
        if 'repos' not in data['data']:
            logger.info("Could not get a list of all repositories. 'repos' is missing in: {}\n".format(data))
        if 'edges' not in data['data']['repos']:
            logger.info("Could not get a list of all repositories. 'edges' is missing in: {}\n".format(data))

        nodes = nodes + data['data']['repos']['edges']

        l = len(data['data']['repos']['edges'])
        last_el = data['data']['repos']['edges'][l-1]
        after = ", after: \"" + last_el['cursor'] + "\""

    data['data']['repos']['edges'] = nodes

    return data['data']['repos']['edges']

def get_all_repos(augur_app, org, totalCount):
    maxCount = 100
    nodes = []
    after = ""

    while totalCount > maxCount or totalCount <= maxCount and totalCount > 0:
        totalCount = totalCount - maxCount
        query = """
        {
            organization(login: "%s") {
                repositories(first: %d%s) {
                    edges {
                        node {
                            id
                            name
                            nameWithOwner
                            url
                            createdAt
                        }
                        cursor
                    }
                }
            }
        }
        """ % (org, maxCount, after)

        data = get_data(augur_app, query, org)
        if 'data' not in data:
            logger.info("Could not get a list of all repositories. 'data' is missing in: {}\n".format(data))
        if 'organization' not in data['data']:
            logger.info("Could not get a list of all repositories. 'organization' is missing in: {}\n".format(data))
        if 'repositories' not in data['data']['organization']:
            logger.info("Could not get a list of all repositories. 'repositories' is missing in: {}\n".format(data))
        if 'edges' not in data['data']['organization']['repositories']:
            logger.info("Could not get a list of all repositories. 'edges' is missing in: {}\n".format(data))

        nodes = nodes + data['data']['organization']['repositories']['edges']

        l = len(data['data']['organization']['repositories']['edges'])
        last_el = data['data']['organization']['repositories']['edges'][l-1]
        after = ", after: \"" + last_el['cursor'] + "\""

    data['data']['organization']['repositories']['edges'] = nodes

    return data['data']['organization']['repositories']['edges']


def get_non_archived_repos_total_count(augur_app, org):
    query = """
    {
        repos: search(query: "user:%s archived:false", type: REPOSITORY) {
                repositoryCount
        }
    }
    """ % (org)

    data = get_data(augur_app, query, org)

    return data['data']['repos']['repositoryCount']

def get_repos_total_count(org, augur_app):
    query = """
    {
        organization(login: "%s") {
            repositories(first: 1) {
                totalCount
            }
        }
    }
    """ % (org)

    data = get_data(augur_app, query, org)

    return data['data']['organization']['repositories']['totalCount']

def get_data(augur_app, query, org):

    # Hit the graphql endpoint and retry 3 times in case of failure
    pc = PlatformConnector()
    pc.logger = logging.getLogger()
    pc.db = augur_app.db
    pc.helper_db = augur_app.helper_db
    pc.init_oauth_keys()

    url = 'https://api.github.com/graphql'
    ROOT_AUGUR_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

    num_attempts = 0
    success = False
    data = None
    while num_attempts < 3:
        logger.info("Hitting endpoint: {} ...\n".format(url))
        r = requests.post(url, json={'query': query}, headers=pc.headers)
        pc.update_gh_rate_limit(pc, r)

        try:
            data = r.json()
        except:
            data = json.loads(json.dumps(r.text))

        if 'errors' in data:
            logger.info("Error!: {}".format(data['errors']))
            if data['errors'][0]['message'] == 'API rate limit exceeded':
                logger.info("Error: Exceeded rate limit for query {}\n".format(query))
                pc.update_gh_rate_limit(pc, r)
                continue

        if 'data' in data:
            success = True
            if 'organization' not in data:
                logger.info("Github response does not contain organization {}\n".format(data))
                break
            data = data['data']['organization']
            if 'repositories' not in data:
                logger.info("Repositories data not provided for organization {}\n".format(org))
                break
            data = data['repositories']
            break
        else:
            logger.info("Request returned a non-data dict: {}\n".format(data))
            if data['message'] == 'Not Found':
                logger.info("Github repo was not found or does not exist for endpoint: {}\n".format(url))
                break
            if data['message'] == 'You have triggered an abuse detection mechanism. Please wait a few minutes before you try again.\n':
                pc.update_gh_rate_limit(pc, r, temporarily_disable=True)
                continue
            if data['message'] == 'Bad credentials\n':
                pc.update_gh_rate_limit(pc, r, bad_credentials=True)
                continue
        num_attempts += 1
    if not success:
        logger.error('Cannot hit endpoint after 3 attempts.\n')
        return

    return data