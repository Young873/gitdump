# -*- coding: utf-8 -*-
import binascii
from urllib.parse import urlparse

__author__ = 'gakki429'

import re
import os
import zlib
import hashlib


def _mkdir(path):
    path = os.path.dirname(path)
    if path and not os.path.exists(path):
        os.makedirs(path)


class GitPack(object):
    """Git Parse Pack Format"""

    def __init__(self, git_path, pack_hash, git_leak_dict):
        self.git_path = git_path
        self.pack_hash = pack_hash
        self.objects = {}  # hash: {type, length}
        self.objects_num = 0

        self.parsed = urlparse(self.git_path)
        self.base_path = './' + self.parsed.hostname + '.' + str(self.parsed.port) + self.parsed.path

        self.idx_path = self.base_path + 'objects/pack/pack-{}.idx'.format(self.pack_hash)
        self.pack_path = self.base_path + 'objects/pack/pack-{}.pack'.format(self.pack_hash)
        self.pack_data = ''
        self.git_leak_dict = git_leak_dict

    def pack_header(self):
        pack = open(self.pack_path, 'rb').read()
        signature = pack[:4]
        if signature == b'PACK':
            # print(22)
            version_number = pack[4:8]
            objects_number = pack[8:12]
            # print(int.from_bytes(objects_number,'big'))
            # print(binascii.b2a_hex(objects_number).decode())
            self.objects_num = int.from_bytes(objects_number, 'big')
            self.pack_data = pack

    def idx_header(self):
        pack_idx = open(self.idx_path, 'rb').read()
        magic_number = pack_idx[:4]
        if magic_number == b'\xfftOc':
            version_number = pack_idx[4:8]
            fan_out_table = pack_idx[8:8 + 1024]  # 网络字节序整数

            pack_hash = pack_idx[-40:-20]
            idx_hash = pack_idx[-20:]

            # Todo: 区分版本（v1，v2），区分idx大小，大于 2g 的 offset 为 8bytes
            idx_data = pack_idx[8 + 1024:-40]
            self.parse_idx(idx_data)

    def split_to_hex(self, length, data):
        length = length * 2
        data_hex_str = binascii.b2a_hex(data).decode()
        # print(data_hex_str[0:20])
        # print(data_hex_str)
        # print(len(data_hex_str))
        # print(length)
        # a7ab5d1025b971316024b84a1706a096b23e9c
        str_len = int(len(data_hex_str) / length)
        # print(len(data_hex_str))
        res_list = []
        # print(str_len)
        for i in range(str_len):
            res_list.append(data_hex_str[i * length:i * length + length])

        # print(len(res_list))
        return res_list

    def parse_idx(self, idx_data):
        num = self.objects_num
        # print(idx_data[:num*20])
        _hashs = self.split_to_hex(20, idx_data[:num * 20])
        # print(_hashs)

        _crcs = self.split_to_hex(4, idx_data[num * 20:num * 24])
        _offsets = self.split_to_hex(4, idx_data[num * 24:])
        for i in range(num):
            self.objects[_hashs[i]] = {'crc': _crcs[i], 'offset': int(_offsets[i], 16)}

    def extract_pack(self):
        # print(self.objects)
        sort_objects = sorted(self.objects.items(), key=lambda x: x[1]['offset'])
        for i in range(len(sort_objects)):
            _hash, _info = sort_objects[i]
            crc = _info['crc']
            offset = _info['offset']
            if i == len(sort_objects) - 1:
                next_offset = -20
            else:
                next_offset = sort_objects[i + 1][1]['offset']
            self.objects[_hash]['data'] = self.pack_data[offset:next_offset]
        self.parse_pack()

    def pack_type(self, num):
        _types = {
            '1': 'commit',
            '2': 'tree',
            '3': 'blob',
            '4': 'tag',
            '6': 'ofs_delta',
            '7': 'ref_delta',
        }
        return _types[str(int(num, 2))]

    def parse_pack(self):

        for _hash, _info in sorted(self.objects.items(), key=lambda x: x[1]['offset']):
            # print(_hash)
            # print(_info)
            _size = []
            try:
                flag, zlib_data = re.search(b'(.*?)(\x78\x9c.*)', _info['data'], re.S).groups()
                # print(flag)
            except AttributeError:
                return

            # for i in range(len(flag)):
            #     # bin_info = bin(int(flag[i].encode('hex'), 16))[2:].rjust(8, '0')
            #     # int.from_bytes(flag, 'big')
            #     bin_info = bin(int.from_bytes(flag, 'big'))[2:].rjust(8, '0')
            #     msb = bin_info[0]
            #     if i == 0:
            #         _type = bin_info[1:4]
            #         _size.append(bin_info[-4:])
            #     else:
            #         _size.append(bin_info[-7:])
            # _length = int(''.join(_size[::-1]), 2)  # 这里其实是小端，不是大端
            # _type = self.pack_type(_type)

            bin_info = bin(int.from_bytes(flag, 'big'))[2:].rjust(8, '0')
            # print('====')
            # print(bin_info)
            _length = bin_info[4:4 + (len(bin_info) // 8 - 1) * 7 + 4]
            # print(_length)
            # _type = int(bin_info[1:4],2)

            try:
                self.objects[_hash]['type'] = self.pack_type(bin_info[1:4])
            except:
                continue
            # self.objects[_hash]['length'] = int(_length,2) # 需要根据length和type来计算sha1 这里计算的不对 大端小端都试了 所以直接使用了解压后的data长度
            self.objects[_hash]['file'] = zlib.decompress(zlib_data)
            self.objects[_hash]['length'] = len(self.objects[_hash]['file'])
            self.objects[_hash]['bin_info'] = flag
            # print(self.objects[_hash]['file']) # 这个不知道文件名啊

    def pack_to_object_file(self):
        for _object in self.objects.values():
            try:
                if _object['type'] != 'blob':
                    continue
                # object_format = '{} {}\x00{}'.format(
                #     _object['type'].encode(), _object['length'], _object['file'])
                object_format = _object['type'].encode() + b' ' + str(_object['length']).encode() + b'\x00' + _object[
                    'file']
                # print(_object['type'], _object['length'], _object['bin_info'], _object['file'])
                # print(object_format)
            except KeyError:
                continue
            sha = hashlib.sha1(object_format).hexdigest()

            path = self.base_path+'objects/{}/{}'.format(sha[:2], sha[2:])
            zlib_object = zlib.compress(object_format)
            dir = path.rsplit('/', 1)[0]
            # print(dir)
            os.makedirs(dir, exist_ok=True)
            open(path, 'wb').write(zlib_object)

            if _object['type'] == 'blob' and sha in self.git_leak_dict:
                blob_path = self.git_leak_dict[sha]['path']
                dir=blob_path.rsplit('/', 1)[0]
                os.makedirs(dir, exist_ok=True)
                try:
                    file = open(blob_path, 'rb').read()
                    if file != _object['file']:
                        filename = '{}.{}'.format(blob_path, sha[:6])
                        with open(filename, 'wb') as f:
                            f.write(_object['file'])
                        f.close()
                        # logger.info('find new file, save file to : {}'.format(filename))
                except FileNotFoundError:
                    with open(blob_path, 'wb') as f:
                        f.write(_object['file'])
                    f.close()
                    # logger.info('saving file to : {}'.format(blob_path))


    def pack_init(self):
        self.pack_header()
        self.idx_header()
        self.extract_pack()
        self.pack_to_object_file()
        # Todo: 重建 ofs_delta，ref_delta
