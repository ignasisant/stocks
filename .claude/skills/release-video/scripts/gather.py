"""Collect PR context with gh: title, body, commits, files, linked Jira keys, and PRs per Jira key."""

import json
import re
import subprocess
import sys
from pathlib import Path

from common import write_json

JIRA_KEY = re.compile(r'\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b')
PR_URL = re.compile(r'github\.com/([^/]+/[^/]+)/pull/(\d+)')
IGNORED_KEYS = {'UTF-8', 'ISO-8859', 'SHA-256', 'TLS-1', 'H-264'}


def _gh(args: list[str]) -> str:
    """
    Run a gh command and return stdout.

    :param args: list[str], gh arguments
    :return: str, command stdout
    """
    res = subprocess.run(['gh', *args], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f'gh {" ".join(args[:3])} failed: {res.stderr.strip()}')
    return res.stdout


def parse_pr(ref: str, default_repo: str) -> tuple[str, str]:
    """
    Split a PR reference into repo and number.

    :param ref: str, PR URL, `owner/repo#123` or bare number
    :param default_repo: str, repo used for bare numbers
    :return: tuple[str, str], (owner/repo, number)
    """
    if m := PR_URL.search(ref):
        return m.group(1), m.group(2)
    if '#' in ref:
        repo, num = ref.split('#', 1)
        return repo, num
    return default_repo, ref.lstrip('#')


def fetch_pr(repo: str, number: str) -> dict:
    """
    Read one PR with the fields the script writer needs.

    :param repo: str, owner/repo
    :param number: str, PR number
    :return: dict, PR facts plus the Jira keys mentioned anywhere in it
    """
    fields = 'number,title,body,state,url,headRefName,baseRefName,mergedAt,author,commits,files,labels'
    pr = json.loads(_gh(['pr', 'view', number, '--repo', repo, '--json', fields]))
    commits = [c['messageHeadline'] for c in pr.get('commits', [])]
    files = [
        {'path': f['path'], 'add': f['additions'], 'del': f['deletions']}
        for f in pr.get('files', [])
    ]
    text = ' '.join([pr['title'], pr.get('body') or '', pr['headRefName'], *commits])
    keys = sorted({k for k in JIRA_KEY.findall(text) if k not in IGNORED_KEYS})
    return {
        'repo': repo,
        'number': pr['number'],
        'url': pr['url'],
        'title': pr['title'],
        'state': pr['state'],
        'merged_at': pr.get('mergedAt'),
        'branch': pr['headRefName'],
        'base': pr['baseRefName'],
        'author': (pr.get('author') or {}).get('login'),
        'labels': [label['name'] for label in pr.get('labels', [])],
        'body': pr.get('body') or '',
        'commits': commits,
        'files': files,
        'jira_keys': keys,
    }


def prs_for_key(key: str, owner: str) -> list[dict]:
    """
    Find PRs in the org that mention a Jira key.

    :param key: str, Jira issue key
    :param owner: str, GitHub org to search
    :return: list[dict], matching PRs (url, title, repo, state)
    """
    out = _gh(
        [
            'search',
            'prs',
            key,
            '--owner',
            owner,
            '--json',
            'url,title,repository,state',
            '--limit',
            '30',
        ]
    )
    return [
        {
            'url': p['url'],
            'title': p['title'],
            'repo': p['repository']['nameWithOwner'],
            'state': p['state'],
        }
        for p in json.loads(out)
    ]


def gather(
    work: Path, prs: list[str], jira: list[str], default_repo: str, owner: str
) -> dict:
    """
    Build contexto.json: every PR, every Jira key and the PRs linked to each key.

    :param work: Path, release work directory
    :param prs: list[str], PR references given by the user
    :param jira: list[str], Jira keys or URLs given by the user
    :param default_repo: str, repo for bare PR numbers
    :param owner: str, GitHub org searched for PRs of a Jira key
    :return: dict, the context written to disk
    """
    seen, items = set(), []
    for ref in prs:
        repo, num = parse_pr(ref, default_repo)
        if (repo, num) not in seen:
            seen.add((repo, num))
            items.append(fetch_pr(repo, num))
    keys = {k for ref in jira for k in JIRA_KEY.findall(ref.upper())}
    keys |= {k for pr in items for k in pr['jira_keys']}
    linked = {k: prs_for_key(k, owner) for k in sorted(keys)}
    ctx = {
        'prs': items,
        'jira_keys': sorted(keys),
        'prs_by_jira_key': linked,
        'jira': {},
    }
    write_json(work / 'contexto.json', ctx)
    return ctx
