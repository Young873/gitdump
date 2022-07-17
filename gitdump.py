import argparse
import logging
import os
import re
import sys
import threading
import traceback
import zlib
from _queue import Empty
from queue import Queue
from urllib.parse import urlparse

import requests
import urllib3

from lib.git_index_parse import parse
from lib.git_packs_parse import GitPack

urllib3.disable_warnings()

global_config = {
    'url': '',
    'thread': 10,
    'only_index': False,
}

hash_path_list = [
    '/logs/HEAD',
    '/logs/refs/heads/master',

    '/packed-refs',
    '/refs/remotes/origin/HEAD',
    '/ORIG_HEAD',
    '/FETCH_HEAD',
    '/refs/wip/index/refs/heads/master',  # PlaidCTF 2020 magit wip mode
    '/refs/wip/wtree/refs/heads/master',
]

# 可能存在敏感信息的路径
info_path_list = [
    '/config',
    '/description',
    '/info/exclude',
    '/COMMIT_EDITMSG',
]

special_path = [
    '/index',
    '/HEAD',
    '/objects/info/packs'
]

git_leak_dict = {}
git_hash_queue = Queue()

FORMATTER = logging.Formatter("\r[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S")
LOGGER_HANDLER = logging.StreamHandler(sys.stdout)
LOGGER_HANDLER.setFormatter(FORMATTER)
logger = logging.getLogger()
logger.addHandler(LOGGER_HANDLER)
logger.setLevel(logging.INFO)

def echo_logo():
    logo='''
        .__  __      .___                    
   ____ |__|/  |_  __| _/_ __  _____ ______  
  / ___\|  \   __\/ __ |  |  \/     \\____ \ 
 / /_/  >  ||  | / /_/ |  |  /  Y Y  \  |_> >
 \___  /|__||__| \____ |____/|__|_|  /   __/ 
/_____/               \/           \/|__|    
                               v1.0.0
    '''
    print(logo)

def cmd_init():
    usage = "gitdump.py [options]\n\tpython3 gitdump.py -u http://xxxxx.com/.git/"
    parser = argparse.ArgumentParser(prog='gitdump', usage=usage)

    parser.add_argument("-u", dest="url", help=".git url", required=True)
    parser.add_argument('-t', "--thread", dest="thread", help="set threads num", default=10,
                        type=int)
    parser.add_argument("--only-index", dest="only_index", help="only parse ./git/index file", default=False,
                        type=bool)

    args = parser.parse_args()
    if args.url:
        global_config['url'] = args.url
    if args.thread:
        global_config['thread'] = args.thread
    if args.only_index:
        global_config['only_index'] = args.only_index


def save_file(file_data, file_name):
    url = global_config['url'].strip('/').strip('/.git') + '/' + file_name.lstrip('/')
    parsed = urlparse(url)
    path = parsed.hostname + '.' + str(parsed.port) + parsed.path
    dir = path.rsplit('/', 1)[0]
    os.makedirs(dir, exist_ok=True)

    with open(path, 'wb') as f:
        f.write(file_data)
    f.close()


def download_file(path):
    url = global_config['url'].strip('/') + '/' + path.lstrip('/')
    parsed = urlparse(url)
    path = './' + parsed.hostname + '.' + str(parsed.port) + parsed.path
    dir = path.rsplit('/', 1)[0]
    os.makedirs(dir, exist_ok=True)
    try:
        response = requests.get(url, stream=True, verify=False)
        if response.status_code == 200:
            chunk_size = 1024 * 4
            with open(path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
            f.close()
            return open(path, 'rb').read()
        else:
            logger.warning("response status 404 : {}".format(url))
    except:
        print(traceback.format_exc())
    return None


def git_hash_parse(data_hash, path=''):
    hash_file_path = '/objects/{}/{}'.format(data_hash[:2], data_hash[2:])
    download_data = download_file(hash_file_path)
    if not download_data:
        return
    try:
        data = zlib.decompress(download_data)
        _type, _len, _file = re.findall(
            rb'^(tag|blob|tree|commit) (\d+?)\x00(.*)', data, re.S | re.M)[0]
        if int(_len) == len(_file):
            if 'type' not in git_leak_dict[data_hash]:
                git_leak_dict[data_hash]['type'] = ''
            git_leak_dict[data_hash]['type'] = _type
            if _type == b'blob':  
                git_blob_parse(_file, data_hash, path)  
            elif _type == b'tree':
                git_tree_parse(_file, path)
            elif _type == b'commit': 
                git_commit_parse(_file)

    except zlib.error:
        logger.error('zlib decompress error')
    except Exception as e:
        print(traceback.format_exc())


def git_file_type(mode):
    if mode in ['160000']:
        return 'commit'
    if mode in ['40000']:
        return 'tree'
    if mode in ['100644', '100664', '100755', '120000']:
        return 'blob'


def git_blob_parse(blob_data, blob_hash, blob_path='', ):
    if blob_path == '':
        blob_path = 'unknown/{}'.format(blob_hash[:6])

    url = global_config['url'].strip('/').strip('/.git') + '/' + blob_path.lstrip('/')
    parsed = urlparse(url)
    blob_path = parsed.hostname + '.' + str(parsed.port) + parsed.path
    dir = blob_path.rsplit('/', 1)[0]
    os.makedirs(dir, exist_ok=True)

    git_leak_dict[blob_hash]['path'] = blob_path
    try:
        file = open(blob_path, 'rb').read()
        if file != blob_data:
            filename = '{}.{}'.format(blob_path, blob_hash[:6])
            with open(filename, 'wb') as f:
                f.write(blob_data)
            f.close()
            logger.info('find new file, save file to : {}'.format(filename))
    except FileNotFoundError:
        with open(blob_path, 'wb') as f:
            f.write(blob_data)
        f.close()
        logger.info('saving file to : {}'.format(blob_path))


def git_tree_parse(tree_data, parent=''):
    try:
        tree = set(re.findall(rb'(\d{5,6}) (.*?)\x00(.{20})', tree_data, re.M | re.S))  
    except TypeError:
        tree = set()
    for _mode, _path, _hash in tree:
        _hash = _hash.hex()
        _path = _path.decode()
        if _hash in git_leak_dict:
            continue
        git_leak_dict[_hash] = {}
        git_hash_parse(_hash, path=parent + '/' + _path)


def git_commit_parse(commit_data):  
    try:
        data_hash = re.findall(rb'[0-9a-z]{40}', commit_data)
        for hash in data_hash:
            hash = hash.decode()
            if hash not in git_leak_dict:
                git_leak_dict[hash] = {}
                git_hash_parse(hash)
    except:
        print(traceback.format_exc())


def run():
    while True:
        try:
            data_hash, path = git_hash_queue.get_nowait()
        except Empty:
            break
        logger.info("start parse hash: {} , progress: {}/{}".format(data_hash, total_qsize - git_hash_queue.qsize(),
                                                                    total_qsize))
        git_hash_parse(data_hash, path)


if __name__ == '__main__':
    echo_logo()
    cmd_init()
    logger.info('config init success.')

    download_data = download_file('/index')
    if download_data:
        parsed = urlparse(global_config['url'] + '/index')
        path = './' + parsed.hostname + '.' + str(parsed.port) + parsed.path

        entry_list = parse(path)
        num = 0
        for entry in entry_list:
            if "sha1" in entry.keys() and entry["sha1"].strip() not in git_leak_dict:
                entry_name = entry["name"].strip()
                entry_sha1=entry["sha1"].strip()
                git_hash_queue.put((entry_sha1, entry_name))
                if entry_sha1 not in git_leak_dict:
                    git_leak_dict[entry_sha1]={}
                git_leak_dict[entry_sha1]['path'] = parsed.hostname + '.' + str(
                    parsed.port) + '/' + entry_name
                num += 1
        logger.info('/index file find hash num : {}'.format(num))

    if not global_config['only_index']:
        download_data = download_file('/HEAD')
        if download_data:
            refs = re.findall(rb'ref: (.*)', download_data, re.M)
            for ref in refs:
                if ref not in hash_path_list:
                    hash_path_list.append(ref.decode())

        for hash_path in hash_path_list:  
            download_data = download_file(hash_path)
            if download_data:
                data_hash_list = re.findall(rb'[0-9a-z]{40}', download_data, re.M)
                logger.info('{} found hash num: {}'.format(hash_path, len(data_hash_list)))
                for data_hash in data_hash_list:
                    data_hash = data_hash.decode() 
                    if data_hash not in git_leak_dict:
                        git_hash_queue.put((data_hash, ''))
                        git_leak_dict[data_hash] = {}

    total_qsize = git_hash_queue.qsize()


    thread_list = []
    for i in range(global_config['thread']):
        t = threading.Thread(target=run, )
        t.start()
        thread_list.append(t)
    for i in thread_list:
        i.join()

    if not global_config['only_index']:
        download_data = download_file('/objects/info/packs')
        if download_data:
            logger.info('find packs, start parse packs')
            packs_hash = re.findall(rb'P pack-([a-z0-9]{40}).pack', download_data, re.S | re.M)
            for pack_hash in packs_hash:
                pack = GitPack(global_config['url'], pack_hash.decode(), git_leak_dict)
                download_file('objects/pack/pack-{}.idx'.format(pack_hash.decode()))
                download_file('objects/pack/pack-{}.pack'.format(pack_hash.decode()))
                pack.pack_init()

        for path in info_path_list:
            logger.info('start download git info files')
            download_file(path)

    logger.info('git dump over')
