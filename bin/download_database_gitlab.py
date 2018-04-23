#!/usr/bin/env python3
import argparse
import json
import os
import sys
from urllib.parse import urlsplit, quote

import requests

# usage:
# ./download_database_gitlab.py https://salsa.debian.org/qa/distro-tracker
# ~/.gitlab-api-token should contain the PRIVATE-TOKEN
# https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html
# gitlab_project_url = 'https://salsa.debian.org/qa/distro-tracker'

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Download database artifact '
                                                 'from latest gitlab job')

    parser.add_argument('gitlab_project_base_url', type=str,
                        help='Base url for distro-tracker project repository.')

    parser.add_argument('download_file_path', type=str, nargs='?',
                        default='./distro-tracker.sqlite',
                        help='Download path for the database artifact.')

    args = parser.parse_args()
    gitlab_project_url = args.gitlab_project_base_url.strip('/') + '/'
    download_file_path = args.download_file_path

    with open(os.path.expanduser('~/.gitlab-api-token')) as token:
        gitlab_private_token = token.readline().strip('\n')

    if gitlab_project_url and download_file_path and gitlab_private_token:
        # Extract base and path from the url argument
        base_url = "{0.scheme}://{0.netloc}/".format(
            urlsplit(gitlab_project_url))
        project_path = "{0.path}".format(urlsplit(gitlab_project_url))

        # Get the gitlab project id for distro-tracker
        headers = {'Content-Type': 'application/json'}
        gitlab_api_url = base_url + 'api/v4/projects/' + \
            quote(project_path.strip('/'), safe='')
        try:
            response = requests.get(
                gitlab_api_url, headers=headers)
        except requests.exceptions.RequestException as e:
            print(e)
            sys.exit(1)

        data = json.loads(response.text)
        if isinstance(data, dict) and 'error' in data.keys():
            # Handle error messages
            print('Response: ' + str(data))
            sys.exit(1)

        gitlab_project_id = data['id']

        # Get the project id for the scheduled job
        headers = {'PRIVATE-TOKEN': gitlab_private_token}
        params = {'name': 'sample-database', 'scope': 'success', 'per_page': 1}
        gitlab_api_url = base_url + 'api/v4/projects/' + str(gitlab_project_id)\
            + '/jobs/'
        try:
            response = requests.get(
                gitlab_api_url, headers=headers, params=params)
        except requests.exceptions.RequestException as e:
            print(e)
            sys.exit(1)

        data = json.loads(response.text)
        if isinstance(data, dict) and 'message' in data.keys():
            # Handle error messages
            print('Response: ' + str(data))
            sys.exit(1)

        job_id = data[0]['id']

        # Download the latest database file
        download_link = base_url + 'api/v4/projects/{0}/jobs/{1}/artifacts/' \
            'data/distro-tracker.sqlite'.format(gitlab_project_id, job_id)

        response = requests.get(download_link, headers=headers, stream=True)
        with open(os.path.expanduser(download_file_path), "wb") as file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    file.write(chunk)
