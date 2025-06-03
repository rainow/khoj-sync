#!/usr/bin/env python3

"""

Welcome to khoj-sync. A tool for ...

Usage:
    khoj-sync [-v | --verbose] init <server> [--api-key=<key>] [--sync-dir=<dir>]
    khoj-sync [-v | --verbose] sync [--once] [--sync-dir=<dir>] [--files-list=<file>]
    khoj-sync [-v | --verbose] list [--sync-dir=<dir>] [--files-list=<file>]
    khoj-sync (-h | --help)
    khoj-sync --version

Options:
    -h --help            Show this screen.
    -v --verbose         Tell me everything you do in excruciating detail.
    --once               Run sync only once, then exit (don't continuously sync).
    --api-key=<key>      API key for authentication with the Khoj server.
    --sync-dir=<dir>     Directory to sync (default: current directory).
    --files-list=<file>  Path to a file containing a list of files to sync (one per line).

"""


import os
import glob
import sys
import csv
import requests
import configparser
import time
import datetime
import json

from docopt import docopt  # command line args parsing: http://docopt.org/


VERBOSE = False

def log(message):
    if VERBOSE: print(message, file=sys.stderr)


CONF_FILENAME = 'khoj-sync.ini'
LOG_FILENAME = 'khoj-sync.log'

DIR = None
SYNC_DIR = None
SERVER = None
FREQUENCY = None
MAX_UPLOADS = None
BATCH_SIZE = None
API_KEY = None

ROOT_CA_FILE = False

# 排除的文件夹列表
EXCLUDED_DIRS = ['node_modules', '.venv', '.git', '.github', '.vscode', '.catpaw', '__pycache__']


def init(server, api_key=None, sync_dir=None):
    log(f'# Setting up {DIR} to sync to the Khoj server at {server}')
    config_path = os.path.join(DIR, CONF_FILENAME)

    config = configparser.ConfigParser()
    config.optionxform = str
    config['config'] = {
        'server': server,
        'frequency': '5m',
        'max-uploads': 10,
        'batch-size': 1,
    }

    # 添加API key到配置
    if api_key:
        config['config']['api-key'] = api_key

    # 添加同步目录到配置
    if sync_dir:
        config['config']['sync-dir'] = sync_dir

    config['sync'] = {
        'last_sync': 'never',
    }

    with open(config_path, 'w') as config_file:
      config.write(config_file)

    # 创建空的日志文件
    log_path = os.path.join(DIR, LOG_FILENAME)
    with open(log_path, 'w') as log_file:
        json.dump({}, log_file)

    log(f'  ... (done)')


def get_files_from_list(files_list_path, sync_dir):
    """从文件列表中读取要同步的文件路径"""
    if not os.path.isfile(files_list_path):
        log(f'Files list not found: {files_list_path}')
        return []

    files = []
    with open(files_list_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):  # 忽略空行和注释
                # 确保路径是相对于同步目录的
                if os.path.isabs(line):
                    # 如果是绝对路径，尝试转换为相对于同步目录的路径
                    try:
                        rel_path = os.path.relpath(line, sync_dir)
                        files.append(rel_path)
                    except ValueError:
                        # 如果路径在不同驱动器上，会抛出ValueError
                        log(f'Skipping file outside sync directory: {line}')
                else:
                    # 如果已经是相对路径，直接添加
                    files.append(line)
    return files

def sync(files_list=None):
    global SYNC_DIR

    log(f'# Syncing files in {SYNC_DIR}...')

    config_path = os.path.join(DIR, CONF_FILENAME)
    log_path = os.path.join(DIR, LOG_FILENAME)

    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(config_path)

    if 'config' not in config or 'server' not in config['config']:
        log('khoj-sync configuration is incomplete. Regenerate with `khoj-sync init <server>`.')
        log('Exiting...')
        return
    server = config['config']['server']

    # 获取API key
    api_key = config['config'].get('api-key')

    if 'sync' not in config:
        config['sync'] = {}
    if 'last_sync' not in config['sync']:
        config['sync']['last_sync'] = 'never'

    # 读取同步日志文件
    sync_files = {}
    try:
        with open(log_path, 'r') as log_file:
            sync_files = json.load(log_file)
    except (FileNotFoundError, json.JSONDecodeError):
        # 如果文件不存在或格式错误，创建新的空日志
        sync_files = {}

    log(f'... to the Khoj server at {config["config"]["server"]}.')

    sync_time = datetime.datetime.now()
    config['sync']['last_sync'] = sync_time.isoformat()

    # 如果指定了文件列表，只同步列表中的文件
    if files_list:
        log(f'Using files list from: {files_list}')
        specific_files = get_files_from_list(files_list, SYNC_DIR)
        log(f'Found {len(specific_files)} files in the list')

        # 验证文件是否存在
        all_files = []
        for path in specific_files:
            full_path = os.path.join(SYNC_DIR, path)
            if os.path.isfile(full_path):
                all_files.append(path)
            else:
                log(f'File not found: {path}')
    else:
        # 否则扫描所有符合条件的文件
        all_files = [
            os.path.relpath(path, start=SYNC_DIR)
            for ext in ['.org', '.md', '.markdown', '.pdf', '.txt', '.rst', '.xml', '.htm', '.html',
                       '.doc', '.docx', '.py', '.js', '.css', '.yaml', '.yml', '.sh', '.json']
            for path in glob.glob(os.path.join(SYNC_DIR, '**', f'*{ext}'), recursive=True)
            if os.path.isfile(path) and os.path.basename(path) not in [CONF_FILENAME, LOG_FILENAME]
            and not any(excluded_dir in os.path.normpath(path).split(os.sep) for excluded_dir in EXCLUDED_DIRS)
        ]

    log('Find any new or updated files to upload.')
    files_to_upload = []

    for path in all_files:
        last_sync_str = sync_files.get(path) or 'never'
        last_sync = None if last_sync_str == 'never' else datetime.datetime.fromisoformat(last_sync_str)

        last_modified = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(SYNC_DIR, path)))

        if last_sync is None or last_modified > last_sync:
            files_to_upload.append(path)

    files_to_upload = files_to_upload[0:MAX_UPLOADS]

    log(f'Now upload any new or updated files (found {len(files_to_upload)}).')
    consecutive_failures = 0
    for i in range(0, len(files_to_upload), BATCH_SIZE):
        batch = files_to_upload[i:i+BATCH_SIZE]

        log(f'    Uploading batch {i} to {i+len(batch)} containing')
        for path in batch:
            log(f'        {path}')

        files = []
        for path in batch:
            name = os.path.relpath(path)
            _, ext = os.path.splitext(path)
            type = {
                '.org': 'text/org',
                '.md': 'text/markdown',
                '.markdown': 'text/markdown',
                '.pdf': 'application/pdf',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.py': 'text/plain',
                '.js': 'text/plain',
                '.css': 'text/plain',
                '.yaml': 'text/plain',
                '.yml': 'text/plain',
                '.sh': 'text/plain',
                '.json': 'text/plain',
            }.get(ext, 'text/plain')
            is_binary = type in ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
            if is_binary:
                file = open(os.path.join(SYNC_DIR, path), 'rb')
            else:
                file = open(os.path.join(SYNC_DIR, path), 'r')
            files.append(("files", (name, file, type)))

        # 准备请求头，添加授权信息
        headers = {}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        response = requests.patch(f'{server}/api/content?client=khoj-sync', files=files, headers=headers, verify=ROOT_CA_FILE)
        if response.status_code == requests.codes.ok:
            for path in batch:
                if os.path.relpath(path) in response.text:
                    sync_files[path] = sync_time.isoformat()
                    log(f'      ... upload of {path} success')
                else:
                    log(f'      ... upload of {path} failed')
            consecutive_failures = 0
        else:
            log(f'    ... upload batch {i} to {i+len(batch)} failed with status code {response.status_code}')
            consecutive_failures += 1

        with open(config_path, 'w') as config_file:
            config.write(config_file)

        # 保存同步日志
        with open(log_path, 'w') as log_file:
            json.dump(sync_files, log_file)

        # If we've failed three times in a row, maybe the server has crashed?
        # Wait 30s to give it time to restart.
        if consecutive_failures > 3:
            time.sleep(30)

        # If we've failed three times in a row and waited 30s to give it time
        # to restart three times, give up with sync up and exit.
        if consecutive_failures > 6:
            sys.exit()

    # 如果使用文件列表，不处理删除操作
    if files_list:
        log('Using files list, skipping deletion check')
        return

    log('Find any previously sync\'d files that are now missing. We need to tell the khoj-server that these have been deleted.')
    files_to_delete = []
    for path, last_sync_str in list(sync_files.items()):
        if path not in all_files:
            if last_sync_str == 'never':
                # We never sync'd this file (for some reason) so we don't need to
                # delete it but we should still remove it from our local state.
                del sync_files[path]
            else:
                # Mark this file to be deleted from the server but wait until that
                # request is successful before deleting it from our config.
                files_to_delete.append(path)

    log(f'Now delete files by updating them to "empty files" (found {len(files_to_delete)}).')
    for i in range(0, len(files_to_delete), BATCH_SIZE):
        batch = files_to_delete[i:i+BATCH_SIZE]

        log(f'    Deleting batch {i} to {i+len(batch)} containing')
        for path in batch:
            log(f'        {path}')

        files = []
        for path in batch:
            name = os.path.relpath(path)
            _, ext = os.path.splitext(path)
            type = {
                '.org': 'text/org',
                '.md': 'text/markdown',
                '.markdown': 'text/markdown',
                '.pdf': 'application/pdf',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.py': 'text/plain',
                '.js': 'text/plain',
                '.css': 'text/plain',
                '.yaml': 'text/plain',
                '.yml': 'text/plain',
                '.sh': 'text/plain',
                '.json': 'text/plain',
            }.get(ext, 'text/plain')
            files.append(("files", (name, "", type)))

        # 准备请求头，添加授权信息
        headers = {}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        response = requests.patch(f'{server}/api/content?client=khoj-sync', files=files, headers=headers, verify=ROOT_CA_FILE)
        if response.status_code == requests.codes.ok:
            consecutive_failures = 0
            for path in batch:
                if os.path.relpath(path) in response.text:
                    del sync_files[path]
                    log(f'      ... deletion of {path} success')
                else:
                    log(f'      ... deletion of {path} failed')
        else:
            log(f'    ... deletion batch {i} to {i+len(batch)} failed with status code {response.status_code}')
            consecutive_failures += 1

        with open(config_path, 'w') as config_file:
            config.write(config_file)

        # 保存同步日志
        with open(log_path, 'w') as log_file:
            json.dump(sync_files, log_file)

        # If we've failed three times in a row, maybe the server has crashed?
        # Wait 30s to give it time to restart.
        if consecutive_failures > 3:
            time.sleep(30)

        # If we've failed three times in a row and waited 30s to give it time
        # to restart three times, give up with sync up and exit.
        if consecutive_failures > 6:
            sys.exit()

    log('(done)')


def sync_continuously(files_list=None):
    while True:
        try:
            sync(files_list)
        except:
            pass
        time.sleep(FREQUENCY)


def list_files(files_list=None):
    global SYNC_DIR

    log(f'# Listing files in {SYNC_DIR} that would be synced...')

    config_path = os.path.join(DIR, CONF_FILENAME)
    log_path = os.path.join(DIR, LOG_FILENAME)

    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(config_path)

    if 'config' not in config or 'server' not in config['config']:
        log('khoj-sync configuration is incomplete. Regenerate with `khoj-sync init <server>`.')
        log('Exiting...')
        return
    server = config['config']['server']

    # 读取同步日志文件
    sync_files = {}
    try:
        with open(log_path, 'r') as log_file:
            sync_files = json.load(log_file)
    except (FileNotFoundError, json.JSONDecodeError):
        # 如果文件不存在或格式错误，创建新的空日志
        sync_files = {}

    # 如果指定了文件列表，只列出列表中的文件
    if files_list:
        log(f'Using files list from: {files_list}')
        specific_files = get_files_from_list(files_list, SYNC_DIR)
        log(f'Found {len(specific_files)} files in the list')

        # 验证文件是否存在
        all_files = []
        for path in specific_files:
            full_path = os.path.join(SYNC_DIR, path)
            if os.path.isfile(full_path):
                all_files.append(path)
            else:
                log(f'File not found: {path}')
                print(f'File not found: {path}')
    else:
        # 否则扫描所有符合条件的文件
        all_files = [
            os.path.relpath(path, start=SYNC_DIR)
            for ext in ['.org', '.md', '.markdown', '.pdf', '.txt', '.rst', '.xml', '.htm', '.html',
                       '.doc', '.docx', '.py', '.js', '.css', '.yaml', '.yml', '.sh', '.json']
            for path in glob.glob(os.path.join(SYNC_DIR, '**', f'*{ext}'), recursive=True)
            if os.path.isfile(path) and os.path.basename(path) not in [CONF_FILENAME, LOG_FILENAME]
            and not any(excluded_dir in os.path.normpath(path).split(os.sep) for excluded_dir in EXCLUDED_DIRS)
        ]

    print(f'Found {len(all_files)} total files in {SYNC_DIR}')

    # 找出需要上传的文件
    files_to_upload = []
    for path in all_files:
        last_sync_str = sync_files.get(path) or 'never'
        last_sync = None if last_sync_str == 'never' else datetime.datetime.fromisoformat(last_sync_str)

        last_modified = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(SYNC_DIR, path)))

        if last_sync is None or last_modified > last_sync:
            files_to_upload.append(path)

    print(f'Files to upload: {len(files_to_upload)}')
    for path in files_to_upload:
        print(f'  {path}')

    # 如果使用文件列表，不处理删除操作
    if files_list:
        print(f'Using files list, skipping deletion check')
        print(f'Total changes: {len(files_to_upload)}')
        return

    # 找出需要删除的文件
    files_to_delete = []
    for path, last_sync_str in list(sync_files.items()):
        if path not in all_files:
            if last_sync_str != 'never':
                files_to_delete.append(path)

    print(f'Files to delete: {len(files_to_delete)}')
    for path in files_to_delete:
        print(f'  {path}')

    print(f'Total changes: {len(files_to_upload) + len(files_to_delete)}')


def load_config():
    global FREQUENCY
    global MAX_UPLOADS
    global BATCH_SIZE
    global API_KEY
    global SYNC_DIR

    path = os.path.join(DIR, CONF_FILENAME)
    if not os.path.isfile(path):
        log('Can\'t load config: {path} does not exist.')
        return False

    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(path)

    if 'config' not in config:
        log('Malformed config file: missing [config] section.')
        return False

    if 'frequency' not in config['config']:
        log('Malformed config file: missing `frequency` setting in [config].')
        return False

    try:
        raw_freq = config['config']['frequency']
        if raw_freq[-1] == 'd':
            FREQUENCY = int(raw_freq[0:-1]) * 60 * 60 * 24
        elif raw_freq[-1] == 'h':
            FREQUENCY = int(raw_freq[0:-1]) * 60 * 60
        elif raw_freq[-1] == 'm':
            FREQUENCY = int(raw_freq[0:-1]) * 60
        elif raw_freq[-1] == 's':
            FREQUENCY = int(raw_freq[0:-1])
        else:
            FREQUENCY = int(raw_freq)
    except:
        log(f'Malformed config file: failed to parse frequency of "{freq}".')
        return False

    if 'max-uploads' not in config['config']:
        log('Malformed config file: missing `max-uploads` setting in [config].')
        return False

    try:
        raw_max_uploads = config['config']['max-uploads']
        MAX_UPLOADS = int(raw_max_uploads)
    except:
        log(f'Malformed config file: failed to parse max-uploads of "{raw_max_uploads}".')
        return False

    try:
        raw_batch_size = config['config']['batch-size']
        BATCH_SIZE = int(raw_batch_size)
    except:
        log(f'Malformed config file: failed to parse batch-size of "{raw_batch_size}".')
        return False

    # 获取API key
    if 'api-key' in config['config']:
        API_KEY = config['config']['api-key']

    # 获取同步目录
    if 'sync-dir' in config['config']:
        SYNC_DIR = os.path.abspath(config['config']['sync-dir'])
    else:
        SYNC_DIR = DIR

    return True


def main():
    arguments = docopt(__doc__, version='khoj-sync 0.1.0')

    global VERBOSE
    VERBOSE = arguments.get('--verbose', False)

    global DIR
    DIR = os.getcwd()

    global SYNC_DIR
    # 默认同步目录为当前目录
    SYNC_DIR = DIR

    # 如果命令行指定了同步目录，优先使用命令行参数
    if arguments.get('--sync-dir'):
        SYNC_DIR = os.path.abspath(arguments.get('--sync-dir'))

    if arguments.get('init', False):
        config_loaded = load_config()
        if config_loaded:
            log(f'Cannot init since a (valid) configuration file already exists.')
            sys.exit(1)
        return init(arguments['<server>'], arguments.get('--api-key'), arguments.get('--sync-dir'))

    elif arguments.get('sync', False):
        config_loaded = load_config()
        if not config_loaded:
            sys.exit(1)

        # 如果命令行指定了同步目录，覆盖配置文件中的设置
        if arguments.get('--sync-dir'):
            SYNC_DIR = os.path.abspath(arguments.get('--sync-dir'))

        log(f'Using sync directory: {SYNC_DIR}')

        # 获取文件列表路径
        files_list = arguments.get('--files-list')

        # 检查是否使用--once参数
        if arguments.get('--once', False):
            return sync(files_list)  # 只运行一次
        else:
            return sync_continuously(files_list)  # 持续运行

    elif arguments.get('list', False):
        config_loaded = load_config()
        if not config_loaded:
            sys.exit(1)

        # 如果命令行指定了同步目录，覆盖配置文件中的设置
        if arguments.get('--sync-dir'):
            SYNC_DIR = os.path.abspath(arguments.get('--sync-dir'))

        log(f'Using sync directory: {SYNC_DIR}')

        # 获取文件列表路径
        files_list = arguments.get('--files-list')

        return list_files(files_list)  # 列出文件但不同步

    else:
        print(arguments)


if __name__ == '__main__':
    main()