#!/usr/bin/env python
# coding=utf-8

class ApplyBeingInviterZset(object):
    _value_unpack = int

    def __init__(self, from_user_id, day_time=None):
        self.from_user_id = from_user_id
        self.day_time = day_time
        self.global_key = self.gen_global_key(from_user_id, day_time)

    @property
    def length(self):
        return ssdb_client.zsize(self.global_key)

    @classmethod
    def gen_global_key(cls, from_user_id, day_time):
        if day_time:
            return 'BeInvCn||%s||%s' % (from_user_id, day_time.strftime("%Y%m%d"))
        else:
            return 'BeInvCn||%s' % from_user_id

    def zexist(self, phone):
        return ssdb_client.zexists(self.global_key, phone)

    def zset(self, phone, create_time):
        value = int(time.mktime(create_time.timetuple()))
        ssdb_client.zset(self.global_key, phone, value)
        day_str_key = self.gen_global_key(self.from_user_id, create_time)
        ssdb_client.zset(day_str_key, phone, value)

    def get_item_ids(self, offset, count):
        items = []
        total = 0
        if offset < 0 or count < 1:
            return items, total

        total = self.length
        tmp_info = ssdb_client.zrange(self.global_key, offset, count)
        items = [fi_item[0] for fi_item in tmp_info]
        return items, total