import os
import re
import zlib
from urllib.parse import urlparse

import requests


def save_file(file_data, file_name):
    url = base_url.strip('/').strip('/.git') + '/' + file_name.lstrip('/')
    print(file_name)
    parsed = urlparse(url)
    path = parsed.hostname + '.' + str(parsed.port) + parsed.path
    dir = path.rsplit('/', 1)[0]
    os.makedirs(dir, exist_ok=True)

    with open(path, 'wb') as f:
        f.write(file_data)
    f.close()

# context = ssl._create_unverified_context()
def download_file(path):
    url = base_url.strip('/') + '/' + path.lstrip('/')
    parsed = urlparse(url)
    path = './'+parsed.hostname + '.' + str(parsed.port) + parsed.path
    dir = path.rsplit('/', 1)[0]
    os.makedirs(dir, exist_ok=True)
    try:
        print('download url : {}'.format(url))
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            chunk_size = 1024*4
            with open(path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
            f.close()
            return open(path,'rb').read()

    except:
        print(traceback.format_exc())
    return None

# 一般情况下 初始hash是获取不到 blob类型吧
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
            git_leak_dict[data_hash] = _type
            if _type == b'blob':  # 如果是blob
                git_blob_parse(_file, data_hash, path)  # 说明是文件 直接保存就完事
            elif _type == b'tree':
                git_tree_parse(_file, path)
            elif _type == b'commit':  # 会指向tree地址 肯定不是commit了
                git_commit_parse(_file)

    # except TypeError:
    #     pass
    # except zlib.error:
    #     pass
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
    # print(blob_hash,blob_path)
    if blob_path == '':
        blob_path = 'unknown/{}'.format(blob_hash[:6])

    url = base_url.strip('/').strip('/.git') + '/' + blob_path.lstrip('/')
    parsed = urlparse(url)
    blob_path = parsed.hostname + '.' + str(parsed.port) + parsed.path
    dir = blob_path.rsplit('/', 1)[0]
    os.makedirs(dir, exist_ok=True)
    try:
        file = open(blob_path, 'rb').read()
        if file != blob_data:
            filename = '{}.{}'.format(blob_path, blob_hash[:6])
            with open(filename, 'wb') as f:
                f.write(blob_data)
            f.close()
    except FileNotFoundError:
        with open(blob_path, 'wb') as f:
            f.write(blob_data)
        f.close()


def git_tree_parse(tree_data, parent=''):
    try:
        tree = set(re.findall(rb'(\d{5,6}) (.*?)\x00(.{20})', tree_data, re.M | re.S))  # 文件类型 文件名称 文件hash
    except TypeError:
        tree = set()
    for _mode, _path, _hash in tree:
        # print(_hash.hex())
        _hash=_hash.hex()
        _path=_path.decode()
        if _hash in git_leak_dict:
            continue
        git_leak_dict[_hash] = {}
        git_hash_parse(_hash, path=parent + '/' + _path)


# 这个就是用来提取hash的
def git_commit_parse(commit_data):  # 如果commit更改了两个文件
    try:
        # data = zlib.decompress(commit_data)
        data_hash = re.findall(rb'[0-9a-z]{40}', commit_data)
        for hash in data_hash:
            hash=hash.decode()
            if hash not in git_leak_dict:
                git_leak_dict[hash] = {}
                git_hash_parse(hash)
    except:
        print(traceback.format_exc())

