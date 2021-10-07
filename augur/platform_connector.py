#SPDX-License-Identifier: MIT
"""
Provides shared functions for connecting to GitHub and GitLab API
"""
import requests, datetime, time, json, os, logging
from logging import Formatter
from multiprocessing import Process
import sqlalchemy as s
import pandas as pd
from urllib.parse import urlparse, quote
from sqlalchemy import MetaData
from augur.config import AugurConfig

class PlatformConnector:

    def __init__(self, config={}, given=[], data_tables=[], operations_tables=[], db=None, helper_db=None, platform="github"):

        ROOT_AUGUR_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

        print(platform)
        self.platform = platform
        self._root_augur_dir = ROOT_AUGUR_DIR
        self.data_tables = data_tables
        self.operations_tables = operations_tables
        self.db = db
        self.helper_db = helper_db

        # if we are finishing a previous task, certain operations work differently
        self.finishing_task = False

        # Update config with options that are general and not specific to any worker
        self.augur_config = AugurConfig(self._root_augur_dir)

        self.config = {
                'gh_api_key': self.augur_config.get_value('Database', 'key'),
                'gitlab_api_key': self.augur_config.get_value('Database', 'gitlab_api_key'),
            }
        self.config.update(self.augur_config.get_section("Logging"))
        self.config.update(config)
        self.given = given

    def initialize_logging(self):
        self.config.update({'log_level' : "INFO"})
        self.config["log_level"] = self.config["log_level"].upper()
        if "debug" in self.config and self.config["debug"]:
            self.config["log_level"] = "DEBUG"

    def find_id_from_login(self, login, platform='github'):
        """
        Retrieves our contributor table primary key value for the contributor with
            the given GitHub login credentials, if this contributor is not there, then
            they get inserted.

        :param login: String, the GitHub login username to find the primary key id for
        :return: Integer, the id of the row in our database with the matching GitHub login
        """
        idSQL = s.sql.text("""
            SELECT cntrb_id FROM contributors WHERE cntrb_login = '{}' \
            AND LOWER(data_source) = '{} api'
            """.format(login, platform))
                
        rs = pd.read_sql(idSQL, self.db, params={})
        data_list = [list(row) for row in rs.itertuples(index=False)]
        try:
            return data_list[0][0]
        except:
            self.logger.info('contributor needs to be added...')

        if platform == 'github':
            cntrb_url = ("https://api.github.com/users/" + login)
        elif platform == 'gitlab':
            cntrb_url = ("https://gitlab.com/api/v4/users?username=" + login )
        self.logger.info("Hitting endpoint: {} ...\n".format(cntrb_url))
        r = requests.get(url=cntrb_url, headers=self.headers)
        self.update_rate_limit(r)
        contributor = r.json()


        company = None
        location = None
        email = None
        if 'company' in contributor:
            company = contributor['company']
        if 'location' in contributor:
            location = contributor['location']
        if 'email' in contributor:
            email = contributor['email']


        if platform == 'github':
            cntrb = {
                'cntrb_login': contributor['login'] if 'login' in contributor else None,
                'cntrb_email': contributor['email'] if 'email' in contributor else None,
                'cntrb_company': contributor['company'] if 'company' in contributor else None,
                'cntrb_location': contributor['location'] if 'location' in contributor else None,
                'cntrb_created_at': contributor['created_at'] if 'created_at' in contributor else None,                
                'cntrb_canonical': None,
                'gh_user_id': contributor['id'] if 'id' in contributor else None,
                'gh_login': contributor['login'] if 'login' in contributor else None,
                'gh_url': contributor['url'] if 'url' in contributor else None,
                'gh_html_url': contributor['html_url'] if 'html_url' in contributor else None,
                'gh_node_id': contributor['node_id'] if 'node_id' in contributor else None,
                'gh_avatar_url': contributor['avatar_url'] if 'avatar_url' in contributor else None,
                'gh_gravatar_id': contributor['gravatar_id'] if 'gravatar_id' in contributor else None,
                'gh_followers_url': contributor['followers_url'] if 'followers_url' in contributor else None,
                'gh_following_url': contributor['following_url'] if 'following_url' in contributor else None,
                'gh_gists_url': contributor['gists_url'] if 'gists_url' in contributor else None,
                'gh_starred_url': contributor['starred_url'] if 'starred_url' in contributor else None,
                'gh_subscriptions_url': contributor['subscriptions_url'] if 'subscriptions_url' in contributor else None,
                'gh_organizations_url': contributor['organizations_url'] if 'organizations_url' in contributor else None,
                'gh_repos_url': contributor['repos_url'] if 'repos_url' in contributor else None,
                'gh_events_url': contributor['events_url'] if 'events_url' in contributor else None,
                'gh_received_events_url': contributor['received_events_url'] if 'received_events_url' in contributor else None,
                'gh_type': contributor['type'] if 'type' in contributor else None,
                'gh_site_admin': contributor['site_admin'] if 'site_admin' in contributor else None,
                'tool_source': self.tool_source,
                'tool_version': self.tool_version,
                'data_source': self.data_source
            }

        elif platform == 'gitlab':
            cntrb =  {
                'cntrb_login': contributor[0]['username'] if 'username' in contributor[0] else None,
                'cntrb_email': email,
                'cntrb_company': company,
                'cntrb_location': location,
                'cntrb_created_at': contributor[0]['created_at'] if 'created_at' in contributor[0] else None,                
                'cntrb_canonical': None,
                'gh_user_id': contributor[0]['id'],
                'gh_login': contributor[0]['username'],
                'gh_url': contributor[0]['web_url'],
                'gh_html_url': None,
                'gh_node_id': None,
                'gh_avatar_url': contributor[0]['avatar_url'],
                'gh_gravatar_id': None,
                'gh_followers_url': None,
                'gh_following_url': None,
                'gh_gists_url': None,
                'gh_starred_url': None,
                'gh_subscriptions_url': None,
                'gh_organizations_url': None,
                'gh_repos_url': None,
                'gh_events_url': None,
                'gh_received_events_url': None,
                'gh_type': None,
                'gh_site_admin': None,
                'tool_source': self.tool_source,
                'tool_version': self.tool_version,
                'data_source': self.data_source
            }
        result = self.db.execute(self.contributors_table.insert().values(cntrb))
        self.logger.info("Primary key inserted into the contributors table: " + str(result.inserted_primary_key))
        self.results_counter += 1
        self.cntrb_id_inc = int(result.inserted_primary_key[0])

        self.logger.info("Inserted contributor: " + cntrb['cntrb_login'] + "\n")

        return self.find_id_from_login(login, platform)

    #doesn't even query the api just gets it based on the url string, can stay in base
    def get_owner_repo(self, git_url):
        """ Gets the owner and repository names of a repository from a git url

        :param git_url: String, the git url of a repository
        :return: Tuple, includes the owner and repository names in that order
        """
        split = git_url.split('/')

        owner = split[-2]
        repo = split[-1]

        if '.git' == repo[-4:]:
            repo = repo[:-4]

        return owner, repo

    def init_oauth_keys(self):
        self.logger.info("Initializing API key.")
        if 'gh_api_key' in self.config or 'gitlab_api_key' in self.config:
            try:
                self.init_oauths(self.platform)
            except AttributeError:
                self.logger.error("Worker not configured to use API key!")
        else:
            self.oauths = [{'oauth_id': 0}]

    def init_oauths(self, platform="github"):
        self.oauths = []
        self.headers = None
        self.logger.info("Trying initialization.")
        # Make a list of api key in the config combined w keys stored in the database
        # Select endpoint to hit solely to retrieve rate limit information from headers of the response
        # Adjust header keys needed to fetch rate limit information from the API responses
        if platform == 'github':
            url = "https://api.github.com/users/gabe-heim"
            oauthSQL = s.sql.text("""
                SELECT * FROM worker_oauth WHERE access_token <> '{}' and platform = 'github'
                """.format(self.config['gh_api_key']))
            key_name = 'gh_api_key'
            rate_limit_header_key = "X-RateLimit-Remaining"
            rate_limit_reset_header_key = "X-RateLimit-Reset"
        elif platform == 'gitlab':
            url = "https://gitlab.com/api/v4/version"
            oauthSQL = s.sql.text("""
                SELECT * FROM worker_oauth WHERE access_token <> '{}' and platform = 'gitlab'
                """.format(self.config['gitlab_api_key']))
            key_name = 'gitlab_api_key'
            rate_limit_header_key = 'ratelimit-remaining'
            rate_limit_reset_header_key = 'ratelimit-reset'

        for oauth in [{'oauth_id': 0, 'access_token': self.config[key_name]}] + json.loads(pd.read_sql(oauthSQL, self.helper_db, params={}).to_json(orient="records")):
            if platform == 'github':
                self.headers = {'Authorization': 'token %s' % oauth['access_token']}
            elif platform == 'gitlab':
                self.headers = {'Authorization': 'Bearer %s' % oauth['access_token']}
            self.logger.debug("Getting rate limit info for oauth: {}\n".format(oauth))
            response = requests.get(url=url, headers=self.headers)
            self.oauths.append({
                    'oauth_id': oauth['oauth_id'],
                    'access_token': oauth['access_token'],
                    'rate_limit': int(response.headers[rate_limit_header_key]),
                    'seconds_to_reset': (datetime.datetime.fromtimestamp(int(response.headers[rate_limit_reset_header_key])) - datetime.datetime.now()).total_seconds()
                })
            self.logger.debug("Found OAuth available for use: {}\n\n".format(self.oauths[-1]))

        if len(self.oauths) == 0:
            self.logger.info("No API keys detected, please include one in your config or in the worker_oauths table in the augur_operations schema of your database\n")

        # First key to be used will be the one specified in the config (first element in
        #   self.oauths array will always be the key in use)
        if platform == 'github':
            self.headers = {'Authorization': 'token %s' % self.oauths[0]['access_token']}
        elif platform == 'gitlab':
            self.headers = {'Authorization': 'Bearer %s' % self.oauths[0]['access_token']}

        self.logger.info("OAuth initialized")

    def update_gitlab_rate_limit(self, response, bad_credentials=False, temporarily_disable=False):
        # Try to get rate limit from request headers, sometimes it does not work (GH's issue)
        #   In that case we just decrement from last recieved header count
        if bad_credentials and len(self.oauths) > 1:
            self.logger.info("Removing oauth with bad credentials from consideration: {}".format(self.oauths[0]))
            del self.oauths[0]

        if temporarily_disable:
            self.logger.info("Gitlab rate limit reached. Temp. disabling...\n")
            self.oauths[0]['rate_limit'] = 0
        else:
            try:
                self.oauths[0]['rate_limit'] = int(response.headers['RateLimit-Remaining'])
            except:
                self.oauths[0]['rate_limit'] -= 1
        self.logger.info("Updated rate limit, you have: " + 
            str(self.oauths[0]['rate_limit']) + " requests remaining.\n")
        if self.oauths[0]['rate_limit'] <= 0:
            try:
                reset_time = response.headers['RateLimit-Reset']
            except Exception as e:
                self.logger.info("Could not get reset time from headers because of error: {}".format(e))
                reset_time = 3600
            time_diff = datetime.datetime.fromtimestamp(int(reset_time)) - datetime.datetime.now()
            self.logger.info("Rate limit exceeded, checking for other available keys to use.\n")

            # We will be finding oauth with the highest rate limit left out of our list of oauths
            new_oauth = self.oauths[0]
            # Endpoint to hit solely to retrieve rate limit information from headers of the response
            url = "https://gitlab.com/api/v4/version"

            other_oauths = self.oauths[0:] if len(self.oauths) > 1 else []
            for oauth in other_oauths:
                self.logger.info("Inspecting rate limit info for oauth: {}\n".format(oauth))
                self.headers = {"PRIVATE-TOKEN" : oauth['access_token']}
                response = requests.get(url=url, headers=self.headers)
                oauth['rate_limit'] = int(response.headers['RateLimit-Remaining'])
                oauth['seconds_to_reset'] = (datetime.datetime.fromtimestamp(int(response.headers['RateLimit-Reset'])) - datetime.datetime.now()).total_seconds()

                # Update oauth to switch to if a higher limit is found
                if oauth['rate_limit'] > new_oauth['rate_limit']:
                    self.logger.info("Higher rate limit found in oauth: {}\n".format(oauth))
                    new_oauth = oauth
                elif oauth['rate_limit'] == new_oauth['rate_limit'] and oauth['seconds_to_reset'] < new_oauth['seconds_to_reset']:
                    self.logger.info("Lower wait time found in oauth with same rate limit: {}\n".format(oauth))
                    new_oauth = oauth

            if new_oauth['rate_limit'] <= 0 and new_oauth['seconds_to_reset'] > 0:
                self.logger.info("No oauths with >0 rate limit were found, waiting for oauth with smallest wait time: {}\n".format(new_oauth))
                time.sleep(new_oauth['seconds_to_reset'])

            # Make new oauth the 0th element in self.oauths so we know which one is in use
            index = self.oauths.index(new_oauth)
            self.oauths[0], self.oauths[index] = self.oauths[index], self.oauths[0]
            self.logger.info("Using oauth: {}\n".format(self.oauths[0]))

            # Change headers to be using the new oauth's key
            self.headers = {"PRIVATE-TOKEN" : self.oauths[0]['access_token']}

    def update_gh_rate_limit(self, response, bad_credentials=False, temporarily_disable=False):
        # Try to get rate limit from request headers, sometimes it does not work (GH's issue)
        #   In that case we just decrement from last recieved header count
        if bad_credentials and len(self.oauths) > 1:
            self.logger.warning("Removing oauth with bad credentials from consideration: {}".format(self.oauths[0]))
            del self.oauths[0]

        if temporarily_disable:
            self.logger.debug("Github thinks we are abusing their api. Preventing use of this key until it resets...\n")
            self.oauths[0]['rate_limit'] = 0
        else:
            try:
                self.oauths[0]['rate_limit'] = int(response.headers['X-RateLimit-Remaining'])
                self.logger.info("Recieved rate limit from headers\n")
            except:
                self.oauths[0]['rate_limit'] -= 1
                self.logger.info("Headers did not work, had to decrement\n")
        self.logger.info("Updated rate limit, you have: " +
            str(self.oauths[0]['rate_limit']) + " requests remaining.\n")
        if self.oauths[0]['rate_limit'] <= 0:
            try:
                reset_time = response.headers['X-RateLimit-Reset']
            except Exception as e:
                self.logger.error("Could not get reset time from headers because of error: {}".format(e))
                reset_time = 3600
            time_diff = datetime.datetime.fromtimestamp(int(reset_time)) - datetime.datetime.now()
            self.logger.info("Rate limit exceeded, checking for other available keys to use.\n")

            # We will be finding oauth with the highest rate limit left out of our list of oauths
            new_oauth = self.oauths[0]
            # Endpoint to hit solely to retrieve rate limit information from headers of the response
            url = "https://api.github.com/users/gabe-heim"

            other_oauths = self.oauths[0:] if len(self.oauths) > 1 else []
            for oauth in other_oauths:
                self.logger.info("Inspecting rate limit info for oauth: {}\n".format(oauth))
                self.headers = {'Authorization': 'token %s' % oauth['access_token']}

                attempts = 3
                success = False
                while attempts > 0 and not success:
                    response = requests.get(url=url, headers=self.headers)
                    try:
                        oauth['rate_limit'] = int(response.headers['X-RateLimit-Remaining'])
                        oauth['seconds_to_reset'] = (datetime.datetime.fromtimestamp(int(response.headers['X-RateLimit-Reset'])) - datetime.datetime.now()).total_seconds()
                        success = True
                    except Exception as e:
                        self.logger.info(f'oath method ran into error getting info from headers: {e}\n')
                        self.logger.info(f'{self.headers}\n{url}\n')
                    attempts -= 1
                if not success:
                    continue

                # Update oauth to switch to if a higher limit is found
                if oauth['rate_limit'] > new_oauth['rate_limit']:
                    self.logger.info("Higher rate limit found in oauth: {}\n".format(oauth))
                    new_oauth = oauth
                elif oauth['rate_limit'] == new_oauth['rate_limit'] and oauth['seconds_to_reset'] < new_oauth['seconds_to_reset']:
                    self.logger.info("Lower wait time found in oauth with same rate limit: {}\n".format(oauth))
                    new_oauth = oauth

            if new_oauth['rate_limit'] <= 0 and new_oauth['seconds_to_reset'] > 0:
                self.logger.info("No oauths with >0 rate limit were found, waiting for oauth with smallest wait time: {}\n".format(new_oauth))
                time.sleep(new_oauth['seconds_to_reset'])

            # Make new oauth the 0th element in self.oauths so we know which one is in use
            index = self.oauths.index(new_oauth)
            self.oauths[0], self.oauths[index] = self.oauths[index], self.oauths[0]
            self.logger.info("Using oauth: {}\n".format(self.oauths[0]))

            # Change headers to be using the new oauth's key
            self.headers = {'Authorization': 'token %s' % self.oauths[0]['access_token']}

    def update_rate_limit(self, response, bad_credentials=False, temporarily_disable=False, platform="gitlab"):
        if platform == 'gitlab':
            return self.update_gitlab_rate_limit(response, bad_credentials=bad_credentials,
                                        temporarily_disable=temporarily_disable)
        elif platform == 'github':
            return self.update_gh_rate_limit(response, bad_credentials=bad_credentials,
                                        temporarily_disable=temporarily_disable)