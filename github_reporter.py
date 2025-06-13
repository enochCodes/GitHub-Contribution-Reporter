#!/usr/bin/env python3
"""
GitHub Contribution Reporter
A tool to extract and report contribution statistics from GitHub repositories.
"""

import requests
import json
import csv
import argparse
from datetime import datetime
import time
import sys
from urllib.parse import urlparse

class GitHubContributionReporter:
    def __init__(self, github_token=None):
        """
        Initialize the reporter with optional GitHub token for higher rate limits.

        Args:
            github_token (str): GitHub personal access token (optional)
        """
        self.base_url = "https://api.github.com"
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Contribution-Reporter'
        }

        if github_token:
            self.headers['Authorization'] = f'token {github_token}'

    def parse_repo_url(self, repo_url):
        """
        Parse GitHub repository URL to extract owner and repo name.

        Args:
            repo_url (str): GitHub repository URL

        Returns:
            tuple: (owner, repo_name)
        """
        try:
            if repo_url.startswith('http'):
                parsed = urlparse(repo_url)
                path_parts = parsed.path.strip('/').split('/')
                if len(path_parts) >= 2:
                    return path_parts[0], path_parts[1]
            else:
                # Handle format like "owner/repo"
                parts = repo_url.split('/')
                if len(parts) == 2:
                    return parts[0], parts[1]

            raise ValueError("Invalid repository URL format")
        except Exception as e:
            raise ValueError(f"Could not parse repository URL: {e}")

    def make_request(self, endpoint, params=None):
        """
        Make API request with error handling and rate limiting.

        Args:
            endpoint (str): API endpoint
            params (dict): Query parameters

        Returns:
            dict: API response data
        """
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.get(url, headers=self.headers, params=params)

            # Handle rate limiting
            if response.status_code == 403 and 'rate limit' in response.text.lower():
                reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                wait_time = max(reset_time - int(time.time()), 0) + 60
                print(f"Rate limit exceeded. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                response = requests.get(url, headers=self.headers, params=params)

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Error making API request: {e}")
            return None

    def get_contributors(self, owner, repo):
        """
        Get list of contributors with their contribution counts.

        Args:
            owner (str): Repository owner
            repo (str): Repository name

        Returns:
            list: List of contributor data
        """
        print(f"Fetching contributors for {owner}/{repo}...")

        contributors = []
        page = 1
        per_page = 100

        while True:
            endpoint = f"/repos/{owner}/{repo}/contributors"
            params = {
                'page': page,
                'per_page': per_page,
                'anon': 'false'  # Exclude anonymous contributors
            }

            data = self.make_request(endpoint, params)
            if not data:
                break

            if not isinstance(data, list) or len(data) == 0:
                break

            contributors.extend(data)

            if len(data) < per_page:
                break

            page += 1
            time.sleep(0.1)  # Small delay to be respectful

        return contributors

    def get_commit_stats(self, owner, repo):
        """
        Get commit statistics for the repository.

        Args:
            owner (str): Repository owner
            repo (str): Repository name

        Returns:
            dict: Commit statistics
        """
        print(f"Fetching commit statistics for {owner}/{repo}...")

        endpoint = f"/repos/{owner}/{repo}/stats/contributors"
        data = self.make_request(endpoint)

        if not data:
            return {}

        # GitHub may return 202 while computing stats
        retries = 3
        while isinstance(data, dict) and data is not None and data.get('message') == 'Statistics not ready' and retries > 0:
            print("Statistics are being computed by GitHub, waiting...")
            time.sleep(5)
            data = self.make_request(endpoint)
            retries -= 1

        return data if isinstance(data, list) else []

    def get_repo_info(self, owner, repo):
        """
        Get basic repository information.

        Args:
            owner (str): Repository owner
            repo (str): Repository name

        Returns:
            dict: Repository information
        """
        endpoint = f"/repos/{owner}/{repo}"
        return self.make_request(endpoint)

    def generate_report(self, repo_url, output_format='csv', output_file=None):
        """
        Generate contribution report for a repository.

        Args:
            repo_url (str): GitHub repository URL
            output_format (str): Output format ('csv', 'json', or 'console')
            output_file (str): Output file path (optional)
        """
        try:
            owner, repo = self.parse_repo_url(repo_url)
            print(f"Analyzing repository: {owner}/{repo}")

            # Get repository info
            repo_info = self.get_repo_info(owner, repo)
            if not repo_info:
                print("Failed to fetch repository information")
                return

            # Get contributors
            contributors = self.get_contributors(owner, repo)
            if not contributors:
                print("No contributors found or failed to fetch contributor data")
                return

            # Get detailed commit stats
            commit_stats = self.get_commit_stats(owner, repo)

            # Merge data
            contribution_data = []
            for contributor in contributors:
                if contributor is None:
                    continue
                username = contributor.get('login', 'Unknown')

                # Fetch user's full name
                user_info = self.make_request(f"/users/{username}")
                full_name = user_info.get('name') if user_info and isinstance(user_info, dict) else ''

                contrib_data = {
                    'username': username,
                    'name': full_name,
                    'contributions': contributor.get('contributions', 0) if contributor else 0,
                    'profile_url': contributor.get('html_url', '') if contributor else '',
                    'avatar_url': contributor.get('avatar_url', '') if contributor else '',
                    'type': contributor.get('type', 'User') if contributor else 'User',
                    'total_commits': 0,
                    'additions': 0,
                    'deletions': 0
                }

                # Add detailed stats if available
                for stat in commit_stats:
                    if stat and isinstance(stat, dict) and stat.get('author', {}) and isinstance(stat.get('author', {}), dict) and stat.get('author', {}).get('login') == username:
                        contrib_data['total_commits'] = sum(week.get('c', 0) for week in stat.get('weeks', []) if week)
                        contrib_data['additions'] = sum(week.get('a', 0) for week in stat.get('weeks', []) if week)
                        contrib_data['deletions'] = sum(week.get('d', 0) for week in stat.get('weeks', []) if week)
                        break

                contribution_data.append(contrib_data)

            # Sort by contributions (descending)
            contribution_data.sort(key=lambda x: x['contributions'], reverse=True)

            # Generate report
            report_data = {
                'repository': {
                    'name': repo_info.get('full_name', f"{owner}/{repo}") if repo_info else f"{owner}/{repo}",
                    'description': repo_info.get('description', '') if repo_info else '',
                    'url': repo_info.get('html_url', '') if repo_info else '',
                    'stars': repo_info.get('stargazers_count', 0) if repo_info else 0,
                    'forks': repo_info.get('forks_count', 0) if repo_info else 0,
                    'language': repo_info.get('language', 'Unknown') if repo_info else 'Unknown',
                    'created_at': repo_info.get('created_at', '') if repo_info else '',
                    'updated_at': repo_info.get('updated_at', '') if repo_info else ''
                },
                'summary': {
                    'total_contributors': len(contribution_data),
                    'total_contributions': sum(c['contributions'] for c in contribution_data),
                    'report_generated': datetime.now().isoformat()
                },
                'contributors': contribution_data
            }

            # Output report
            if output_format.lower() == 'json':
                self._output_json(report_data, output_file)
            elif output_format.lower() == 'csv':
                self._output_csv(report_data, output_file)
            else:
                self._output_console(report_data)

        except Exception as e:
            print(f"Error generating report: {e}")

    def _output_json(self, data, output_file):
        """Output report as JSON."""
        filename = output_file or f"contribution_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Report saved to: {filename}")

    def _output_csv(self, data, output_file):
        """Output report as CSV."""
        filename = output_file or f"contribution_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow([
                'Username', 'Name', 'Contributions', 'Total Commits',
                'Additions', 'Deletions', 'Profile URL', 'Type'
            ])

            # Write contributor data
            for contrib in data['contributors']:
                writer.writerow([
                    contrib.get('username', ''),
                    contrib.get('name', ''),
                    contrib.get('contributions', 0),
                    contrib.get('total_commits', ''),
                    contrib.get('additions', ''),
                    contrib.get('deletions', ''),
                    contrib.get('profile_url', ''),
                    contrib.get('type', '')
                ])

        print(f"Report saved to: {filename}")

    def _output_console(self, data):
        """Output report to console."""
        repo = data['repository']
        summary = data['summary']

        print("\n" + "="*80)
        print(f"CONTRIBUTION REPORT: {repo['name']}")
        print("="*80)
        print(f"Description: {repo['description']}")
        print(f"URL: {repo['url']}")
        print(f"Stars: {repo['stars']} | Forks: {repo['forks']} | Language: {repo['language']}")
        print(f"Created: {repo['created_at'][:10]} | Updated: {repo['updated_at'][:10]}")
        print(f"\nTotal Contributors: {summary['total_contributors']}")
        print(f"Total Contributions: {summary['total_contributions']}")
        print(f"Report Generated: {summary['report_generated'][:19]}")

        print("\n" + "-"*80)
        print("TOP CONTRIBUTORS:")
        print("-"*80)
        print(f"{'Rank':<4} {'Username':<20} {'Name':<25} {'Contributions':<12} {'Type':<8}")
        print("-"*80)

        for i, contrib in enumerate(data['contributors'][:20], 1):  # Top 20
            print(f"{i:<4} {contrib['username'][:19]:<20} {contrib.get('name', '')[:24]:<25} "
                  f"{contrib['contributions']:<12} {contrib.get('type', 'User'):<8}")


def main():
    parser = argparse.ArgumentParser(description='GitHub Contribution Reporter')
    parser.add_argument('repo_url', help='GitHub repository URL or owner/repo format')
    parser.add_argument('-t', '--token', help='GitHub personal access token (for higher rate limits)')
    parser.add_argument('-f', '--format', choices=['csv', 'json', 'console'],
                       default='console', help='Output format (default: console)')
    parser.add_argument('-o', '--output', help='Output file path (optional)')

    args = parser.parse_args()

    # Create reporter instance
    reporter = GitHubContributionReporter(args.token)

    # Generate report
    reporter.generate_report(args.repo_url, args.format, args.output)


if __name__ == "__main__":
    main()
