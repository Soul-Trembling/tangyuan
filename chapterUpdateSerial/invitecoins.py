# -*- coding: utf-8 -*-
import sys
import traceback
import time
import random
import datetime
import ujson as json
from bottle import cheetah_view as view, get, post, redirect, request, abort
from ricebag.model.asset import ManualCharge, CoinAccountTrade, CoinAccountCharge, CoinAccount, UserCoinAccountTradeZSet
from ricebag.model.notice import Notice
from ricebag.model.userbind import PhoneBind
from ricebag.model.weixin import WeixinFacade
from ricebag.searchmodel import SearchUpdateNotification
from riceball.storage import storage
from riceball.storage.xmodel import XModelObject, model_config, xfield
from riceball.storage.xmodel.engine import CachedEngine, MysqlEngine, SsdbEngine
from riceball.storage.client import ssdb as ssdb_client, mysql as mysql_client
from ricebag.model.user import User
from riceball.tools.text import tounicode, tobytes
from ricebag.error import Error
from riceball.options import settings
from riceball.tools import cached, rand
from ricebag.model.manage import ManageEmail
from riceball.tools.assertion import assert_equals
from application.action import check_login
from ricebag import dict_result, jsonp, param

if settings.env_name != "online":
    DOMAIN = "test.itangyuan.com"
else:
    DOMAIN = "i.itangyuan.com"

# [INVITE_BEGIN_TIME, INVITE_END_TIME)

INVITE_BEGIN_TIME = datetime.datetime(2016, 5, 1)
INVITE_END_TIME = datetime.datetime(2016, 6, 1)

CHARGE_MANAGE_ID = ManageEmail.get("activity@chineseall.com").id
CHARGE_ACT_TYPE = ManualCharge.ACT_TYPE_INVITE_COINS

BEINVITE_COINS_WEIGHT = [
    (233, 60),
    (333, 30),
    (456, 5),
    (518, 2),
    (666, 1),
    (777, 1),
    (888, 1),
    (999, 0),
]

BEINVITE_COINS_RANDOM_LIST = sum([[fi_id] * fi_weight for fi_id, fi_weight in BEINVITE_COINS_WEIGHT], [])

BEINVITE_INVITE_COINS = {
    233: 168,
    333: 188,
    456: 233,
    518: 218,
    666: 333,
    777: 456,
    888: 518,
    999: 520,
}


def get_now_datetime():
    now = datetime.datetime.now()
    # now = datetime.datetime(2016, 4, 30)
    return now


def get_be_inviter_random_coins():
    return random.choice(BEINVITE_COINS_RANDOM_LIST)


@storage()
class HdBeingInviterCoins(XModelObject):
    """
    被邀请者金币信息
    """
    model_config = model_config('phone', auto_creatable=True)
    model_engine = CachedEngine.mysql_object(table='huodong_being_inviter_coins')

    STATUS_REGIST = 0x01  # 是否注册成功
    STATUS_UNREGIST = 0xFE

    STATUS_MEET = 0x02  # 是否满足要求
    STATUS_UNMEET = 0xFD

    STATUS_PASS = 0x04  # 是否处理过
    STATUS_UNPASS = 0xFB

    phone = xfield.str('')
    user_id = xfield.int(0)
    from_user_id = xfield.int(0)
    coins = xfield.int(0)
    status = xfield.int(0)
    device_id = xfield.unicode(u'')
    create_time = xfield.datetime(datetime.datetime.now)
    regist_time = xfield.datetime(datetime.datetime.now)
    remote_addr = xfield.str('')
    processed = xfield.int(0)
    TIME_OUT_DAYS = 3
    ONE_DAY_MAX_NUM = 100

    @classmethod
    def update_regist_info(cls, phone, user_id, device_id):
        phone_obj = cls.fetch(phone)
        if not phone_obj:
            return
        if phone_obj.processed or phone_obj.regist or phone_obj.device_id:
            return

        if not device_id:
            phone_obj.user_id = user_id
            phone_obj.regist = True
            phone_obj.meet = False
            phone_obj.save()
            return

        if phone_obj.timeout:
            phone_obj.user_id = user_id
            phone_obj.regist = True
            phone_obj.meet = False
            phone_obj.regist_time = datetime.datetime.now()
            phone_obj.save()
            return

        sql = 'SELECT EXISTS(SELECT 1 FROM`huodong_being_inviter_coins`WHERE`device_id`=%s)'
        has_device_id = bool(mysql_client.count(sql, device_id))
        if has_device_id:
            phone_obj.user_id = user_id
            phone_obj.regist = True
            phone_obj.meet = False
            phone_obj.device_id = device_id
            phone_obj.regist_time = datetime.datetime.now()
            phone_obj.save()
        else:
            phone_obj.user_id = user_id
            phone_obj.regist = True
            phone_obj.meet = True
            phone_obj.device_id = device_id
            phone_obj.regist_time = datetime.datetime.now()
            phone_obj.save()

    @property
    def regist(self):
        return self.status & self.STATUS_REGIST > 0

    @regist.setter
    def regist(self, regist):
        if regist:
            self.status |= self.STATUS_REGIST
        else:
            self.status &= self.STATUS_UNREGIST

    @property
    def meet(self):
        return self.status & self.STATUS_MEET > 0

    @meet.setter
    def meet(self, meet):
        if meet:
            self.status |= self.STATUS_MEET
        else:
            self.status &= self.STATUS_UNMEET

    @property
    def is_pass(self):
        return self.status & self.STATUS_PASS > 0

    @is_pass.setter
    def is_pass(self, is_pass):
        if is_pass:
            self.status |= self.STATUS_PASS
        else:
            self.status &= self.STATUS_UNPASS

    @property
    def timeout(self):
        if not self.regist:
            return (datetime.datetime.now() - self.create_time).days >= self.TIME_OUT_DAYS
        else:
            regist_time = self.regist_time or datetime.datetime.now()
            return (regist_time - self.create_time).days >= self.TIME_OUT_DAYS

    @classmethod
    def check_and_fetch(cls, key, auto_create=False, from_user_id=0):
        bind = PhoneBind.get(key)
        if bind:
            return u"这个手机号已经注册过汤圆咯<br>快登录汤圆邀请好友赚金币", None
        obj = cls.fetch(key, auto_create=False)
        if obj:
            if obj.timeout:
                return None, obj
            return u"""已领取<b class="nickname">%s</b>的金币红包<br>%s即将过期"""\
                   % (tounicode(obj.from_user_nickname), tounicode(obj.disable_time_str)), obj
        if auto_create:
            remote_addr = request.remote_addr
            if ForbidBeingInviterIp.exist_ip(remote_addr):
                return u"当前限制领取", None
            create_time = datetime.datetime.now()
            today_mem_num = ApplyBeingInviterZset(from_user_id, create_time).length
            if today_mem_num >= cls.ONE_DAY_MAX_NUM:
                return u"你的好友今日邀请名额已用完咯，明天再来吧！", None
            obj = cls.fetch(key, auto_create=True)
            if obj:
                obj.coins = get_be_inviter_random_coins()
                obj.from_user_id = from_user_id
                obj.remote_addr = remote_addr
                obj.save()
                return None, obj
            else:
                return u"信息有误", None

    @property
    def disable_time(self):
        return self.create_time + datetime.timedelta(days=self.TIME_OUT_DAYS)

    @property
    def disable_time_str(self):
        return self.disable_time.strftime("%m月%d日 %H:%M")

    @property
    def from_user_nickname(self):
        user = User.get(self.from_user_id or 0)
        user_nickname = u""
        if user:
            user_nickname = user.nickname
        return user_nickname

    def save(self):
        XModelObject.save(self)
        if self.from_user_id:
            tmp_zset = ApplyBeingInviterZset(self.from_user_id)
            if not tmp_zset.zexist(self.phone):
                tmp_zset.zset(self.phone, self.create_time)


class ForbidBeingInviterIp(object):

    @classmethod
    def gen_global_key(cls):
        return "ForbidBeingInviterIp"

    @classmethod
    def exist_ip(cls, remote_addr):
        str_key = cls.gen_global_key()
        return ssdb_client.zexists(str_key, remote_addr)

    @classmethod
    def add_forbid_ip(cls, remote_addr):
        str_key = cls.gen_global_key()
        value = int(time.time())
        ssdb_client.zset(str_key, remote_addr, value)

    @classmethod
    def del_forbid_ip(cls, remote_addr):
        str_key = cls.gen_global_key()
        ssdb_client.zdel(str_key, remote_addr)


class ForbidBeingInviterUser(object):

    @classmethod
    def gen_global_key(cls):
        return "ForbidBeingInviterUser"

    @classmethod
    def exist_uid(cls, uid):
        str_key = cls.gen_global_key()
        return ssdb_client.zexists(str_key, uid)

    @classmethod
    def add_forbid_uid(cls, uid):
        str_key = cls.gen_global_key()
        value = int(time.time())
        ssdb_client.zset(str_key, uid, value)

    @classmethod
    def del_forbid_uid(cls, uid):
        str_key = cls.gen_global_key()
        ssdb_client.zdel(str_key, uid)

    @classmethod
    def all_forb_uids(cls):
        gen_items = ssdb_client.zrange(cls.gen_global_key(), 0, -1)
        return [int(fi_item[0]) for fi_item in gen_items]


class InviterRankZset(object):

    RANK_TOTAL = 0
    RANK_TODAY = 1
    RANK_YESTERDAY = 2

    MAX_NUM = 100

    def __init__(self, rank_id):
        self.rank_id = rank_id

    @property
    def gen_global_key(self):
        return "HdInviterRank||%s" % self.rank_id

    def rank_index_str(self, uid):
        tmp_rank = ssdb_client.zrrank(self.gen_global_key, uid)
        if tmp_rank is None:
            return "%s+" % self.MAX_NUM
        return tmp_rank + 1

    def all_uids(self):
        gen_items = ssdb_client.zrange(self.gen_global_key, 0, -1)
        return [int(fi_item[0]) for fi_item in gen_items]

    def get_items(self, offset=0, limit=20):
        items = []
        gen_items = ssdb_client.zrrange(self.gen_global_key, offset, limit)
        for fi_uid, fi_num in gen_items:
            user = User.get(int(fi_uid) or 0)
            if not user:
                continue
            items.append({
                'nickname': user.nickname,
                'num': int(fi_num)
            })
        return items

    def add(self, uid, num):
        ssdb_client.zset(self.gen_global_key, uid, num)

    def del_uid(self, uid):
        str_key = self.gen_global_key
        ssdb_client.zdel(str_key, uid)

    @classmethod
    def get_rank_members(cls):
        gen_key = "HdInviterRank||Members"
        tmp_value = ssdb_client.get(gen_key)
        try:
            rank_members = json.loads(tmp_value)
        except:
            rank_members = None
        return rank_members or {"total" : [],
                                "today": [],
                                "yesterday": []}

    @classmethod
    def set_rank_members(cls, rank_members):
        tmp_value = json.dumps(rank_members)
        gen_key = "HdInviterRank||Members"
        ssdb_client.set(gen_key, tmp_value)

    @classmethod
    def get_rank_by_day(cls, day_time):
        if not isinstance(day_time, datetime.datetime):
            raise
        select_sql = ("select user_id,count(*) as num, max(create_time) as max_create_time from huodong_inviter_coins "
                          " where processed=1 and to_days(create_time) = to_days(%s) group by user_id order by "
                          " num desc,max_create_time limit %s")
        result = mysql_client.query(select_sql, day_time, 500)
        forb_uids = ForbidBeingInviterUser.all_forb_uids()
        rank_list = []
        for fi_row in result:
            user_id = fi_row["user_id"]
            num = fi_row["num"]
            last_inv_time = fi_row["max_create_time"]
            if user_id in forb_uids:
                continue
            user = User.get(user_id)
            if not user:
                continue
            rank_list.append({
                "user_id": user_id,
                "nickname": user.nickname,
                "num": num,
                "last_inv_time": last_inv_time,
            })
        return rank_list

    @classmethod
    def rebuild_all(cls):
        gen_select_sql = ("select user_id,count(*) as num, max(create_time) as max_create_time from huodong_inviter_coins "
                          "where processed=1 %s group by user_id order by num desc,max_create_time limit %s")
        sql_info = [
            {
              "rank_key": "total",
              "rank_id": cls.RANK_TOTAL,
              "select_sql": gen_select_sql % ("", 500),
              "sql_parms": [],
            },

            {
              "rank_key": "today",
              "rank_id": cls.RANK_TODAY,
              "select_sql": gen_select_sql % ("and to_days(create_time) = to_days(%s)", 500),
              "sql_parms": [datetime.datetime.now()],
            },

            {
              "rank_key": "yesterday",
              "rank_id": cls.RANK_YESTERDAY,
              "select_sql": gen_select_sql % ("and to_days(create_time) = to_days(%s)", 500),
              "sql_parms": [datetime.datetime.now() + datetime.timedelta(days=-1)],
            },

        ]

        members = {
            "total" : [],
            "today": [],
            "yesterday": [],
        }
        forb_uids = ForbidBeingInviterUser.all_forb_uids()
        for fi_info in sql_info:
            rank_key = fi_info["rank_key"]
            rank_id = fi_info["rank_id"]
            select_sql = fi_info["select_sql"]
            sql_parms = fi_info["sql_parms"]
            result = mysql_client.query(select_sql, *sql_parms)
            zset_obj = cls(rank_id)
            has_ids = zset_obj.all_uids()
            new_ids = []
            has_num = 0
            for fi_row in result:
                user_id = fi_row["user_id"]
                user = User.get(user_id)
                if not user:
                    continue
                if user_id in forb_uids:
                    continue
                if has_num > 100:
                    break
                has_num += 1
                num = int(fi_row["num"])
                max_create_time = fi_row["max_create_time"]
                max_create_time_value = int(max_create_time.strftime("%s"))
                sort_value = (num << 32) - max_create_time_value
                zset_obj.add(user_id, sort_value)
                new_ids.append(user_id)
                if has_num > 20:
                    continue
                members[rank_key].append({
                    "nickname": user.nickname,
                    "num": num,
                })

            for fi_uid in has_ids:
                if fi_uid not in new_ids:
                    zset_obj.del_uid(fi_uid)
        for fi_key, fi_value in members.items():
            value_len = len(fi_value)
            fi_value.extend([{"nickname": u"空无一人", "num": -1}] * (20 - value_len))
        cls.set_rank_members(members)


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


@storage()
class HdInviterCoins(XModelObject):
    """
    邀请者金币信息
    """
    model_config = model_config(('user_id', 'new_user_id'), auto_creatable=True)
    model_engine = MysqlEngine.object(table='huodong_inviter_coins')

    id = xfield.int(0)
    user_id = xfield.int(0)
    new_user_id = xfield.int(0)
    coins = xfield.int(0)
    create_time = xfield.datetime(datetime.datetime.now)
    processed = xfield.int(0)

    @classmethod
    def raw_insert(cls, conn, user_id, new_user_id, coins, create_time, processed=0):
        sql = ('INSERT INTO `huodong_inviter_coins`'
               '(`user_id`,`new_user_id`,`coins`,`create_time`,`processed`)'
               'VALUES(%s,%s,%s,%s,%s)')
        row_count, charge_id = conn.execute(
            sql, user_id, new_user_id, coins, create_time, processed)
        return row_count, charge_id


def processed_invite_coins(be_inviter_phone):
    """
    送金币
    被邀请者注册后 --> 检测状态 --> 赠送被邀请者金币 --> 邀请者金币获取 --> 赠送邀请者金币
    :param be_inviter_phone: 被邀请者 手机号
    :return:
    """
    be_inviter_obj = HdBeingInviterCoins.fetch(be_inviter_phone)
    if not be_inviter_obj:
        return u"手机号不存在"
    if be_inviter_obj.processed or be_inviter_obj.is_pass:
        return u"请勿重复处理金币"
    user = User.get(be_inviter_obj.user_id or 0)
    if not user or not user.coin_account:
        return u"用户不存在"
    from_user = User.get(be_inviter_obj.from_user_id or 0)
    if not from_user or not from_user.coin_account:
        return u"邀请人不存在"
    if not be_inviter_obj.regist or not be_inviter_obj.user_id:
        return u"还未注册"
    if be_inviter_obj.timeout:
        be_inviter_obj.is_pass = True
        be_inviter_obj.save()
        notice_body = u'金币领取超时已溜走，邀请好友来注册赚金币吧'
        Notice.put_plain(be_inviter_obj.user_id, notice_body, action=None)
        return u"规定时间内未注册"
    if not be_inviter_obj.meet:
        be_inviter_obj.is_pass = True
        be_inviter_obj.save()
        notice_body = u'抱歉，金币领取失败，当前设备已领取过金币奖励，不可重复领取，你可以邀请好友注册赚金币哦'
        Notice.put_plain(be_inviter_obj.user_id, notice_body, action=None)
        return u"不满足要求"

    be_inviter_coins = be_inviter_obj.coins
    if be_inviter_coins < 1:
        return u"被邀请人金币不符合要求"
    inviter_coins = BEINVITE_INVITE_COINS.get(be_inviter_obj.coins, 0)
    if inviter_coins < 1:
        return u"邀请人金币不符合要求"

    now = datetime.datetime.now()

    # 送两者金币
    with mysql_client.get_connection(auto_commit=False) as conn:
        conn.execute('START TRANSACTION')
        try:
            # 第一步设置 processed 标识，是为了尽早的失败
            sql = ('update `huodong_being_inviter_coins` '
                   'set `processed`=1 where `phone`=%s and `processed`=0')
            row_count, _ = conn.execute(sql, be_inviter_phone)
            assert_equals(1, row_count, 'row_count')

            reason_be_inviter = u"新用户注册活动奖励"
            # 被邀请人金币 begin
            row_count, new_id_be_inviter = ManualCharge.raw_insert(conn, be_inviter_obj.user_id, be_inviter_coins,
                                                                   reason_be_inviter, CHARGE_MANAGE_ID,
                                                                   be_inviter_obj.from_user_id,
                                                                   CHARGE_ACT_TYPE, now, processed=1)
            assert_equals(1, row_count, 'row_count')

            sn = CoinAccountTrade.gen_serial_number(now, CoinAccountTrade.EVENT_CHARGE)

            # 被邀请人充值记录
            row_count, charge_id_be_inviter = CoinAccountCharge.raw_insert(
                conn, be_inviter_obj.user_id, ManualCharge.TYPE, new_id_be_inviter,
                be_inviter_coins, CoinAccountCharge.PLATFORM_MANUAL, now)
            assert_equals(1, row_count, 'row_count')

            # 被邀请人金币交易记录
            row_count, trade_id_be_inviter = CoinAccountTrade.raw_insert(
                conn, sn, be_inviter_obj.user_id, CoinAccountTrade.FLOW_IN,
                be_inviter_coins, CoinAccountTrade.EVENT_CHARGE, charge_id_be_inviter,
                '{}', now)
            assert_equals(1, row_count, 'row_count')

            # 被邀请人金币额度
            row_count, new_balance = CoinAccount.raw_incr(
                conn, be_inviter_obj.user_id, be_inviter_coins)
            assert_equals(1, row_count, 'row_count')
            # 被邀请人金币 end

            # 邀请人金币 begin
            reason_inviter = u"邀请新用户活动奖励"
            row_count, new_id_inviter = HdInviterCoins.raw_insert(conn, be_inviter_obj.from_user_id,
                                                                  be_inviter_obj.user_id, inviter_coins, now,
                                                                  processed=1)
            assert_equals(1, row_count, 'row_count')

            row_count, new_id_inviter = ManualCharge.raw_insert(conn, be_inviter_obj.from_user_id, inviter_coins,
                                                                reason_inviter, CHARGE_MANAGE_ID,
                                                                be_inviter_obj.user_id,
                                                                CHARGE_ACT_TYPE, now, processed=1)
            assert_equals(1, row_count, 'row_count')

            sn = CoinAccountTrade.gen_serial_number(now, CoinAccountTrade.EVENT_CHARGE)

            # 邀请人充值记录
            row_count, charge_id_inviter = CoinAccountCharge.raw_insert(
                conn, be_inviter_obj.from_user_id, ManualCharge.TYPE, new_id_inviter,
                inviter_coins, CoinAccountCharge.PLATFORM_MANUAL, now)
            assert_equals(1, row_count, 'row_count')

            # 邀请人金币交易记录
            row_count, trade_id_inviter = CoinAccountTrade.raw_insert(
                conn, sn, be_inviter_obj.from_user_id, CoinAccountTrade.FLOW_IN,
                inviter_coins, CoinAccountTrade.EVENT_CHARGE, charge_id_inviter,
                '{}', now)
            assert_equals(1, row_count, 'row_count')

            # 邀请人金币额度
            row_count, new_balance = CoinAccount.raw_incr(
                conn, be_inviter_obj.from_user_id, inviter_coins)
            assert_equals(1, row_count, 'row_count')
            # 邀请人金币 end

            conn.execute('COMMIT')

        except Exception, e:
            print "----- phone,error:", be_inviter_phone, e
            traceback.print_exc()
            conn.execute('ROLLBACK')
            return tounicode(str(e))

    # 处理缓存
    HdBeingInviterCoins.model_engine.clear_cache(be_inviter_obj.phone)
    CoinAccount.model_engine.clear_cache(be_inviter_obj.user_id)
    CoinAccount.model_engine.clear_cache(be_inviter_obj.from_user_id)
    # noinspection PyUnboundLocalVariable
    CoinAccountTrade.model_engine.clear_cache(trade_id_be_inviter)
    CoinAccountTrade.model_engine.clear_cache(trade_id_inviter)
    # noinspection PyUnboundLocalVariable
    CoinAccountCharge.model_engine.clear_cache(charge_id_be_inviter)
    CoinAccountCharge.model_engine.clear_cache(charge_id_inviter)

    UserCoinAccountTradeZSet.get(be_inviter_obj.user_id).add(
        trade_id_be_inviter, int(time.mktime(now.timetuple())))
    SearchUpdateNotification.send(SearchUpdateNotification.MODEL_NAME_USER, be_inviter_obj.user_id,
                                  SearchUpdateNotification.ACTION_UPDATE)

    UserCoinAccountTradeZSet.get(be_inviter_obj.from_user_id).add(
        trade_id_inviter, int(time.mktime(now.timetuple())))
    SearchUpdateNotification.send(SearchUpdateNotification.MODEL_NAME_USER, be_inviter_obj.from_user_id,
                                  SearchUpdateNotification.ACTION_UPDATE)

    # 发消息
    notice_body = u'恭喜你，邀请新用户活动奖励%s金币已到账！' % be_inviter_coins
    Notice.put_plain(be_inviter_obj.user_id, notice_body, action=None)

    notice_body = u'恭喜你，邀请新用户活动奖励%s金币已到账！' % inviter_coins
    Notice.put_plain(be_inviter_obj.from_user_id, notice_body, action=None)


def processed_current_invite_coins(mylogger=None):
    select_sql = ("select `phone` from `huodong_being_inviter_coins` "
                  " where `processed`=0 "
                  " and `status`&%s = %s ")
    result = mysql_client.query(
        select_sql,
        (HdBeingInviterCoins.STATUS_REGIST | HdBeingInviterCoins.STATUS_PASS),
        HdBeingInviterCoins.STATUS_REGIST)

    for fi_row in result:
        be_inviter_phone = fi_row["phone"]
        err_msg = processed_invite_coins(be_inviter_phone)
        if mylogger:
            if err_msg:
                mylogger.error(u"phone:%s error:%s" % (be_inviter_phone, err_msg))
            else:
                mylogger.info("phone:%s success" % be_inviter_phone)


##### api

@get('/activity/invitecoins/status_avalon.js')
@jsonp
@check_login(False)
def invitecoins_status():
    tips = ""
    available_flag = False
    check_time = get_now_datetime()
    if check_time < INVITE_BEGIN_TIME:
        tips = u"活动未开始"
    elif check_time > INVITE_END_TIME:
        tips = u"活动已结束"
    else:
        available_flag = True

    user_id = (request.uid if hasattr(request, 'uid') else 0) or 0
    today_invite_rank = "100+"
    share_click_url = ""
    if user_id:
        today_invite_rank = InviterRankZset(InviterRankZset.RANK_TODAY).rank_index_str(user_id)
        share_click_url = "http://%s/huodong/invitecoins/share/%s.html" % (DOMAIN, user_id)

    if user_id:
        phone_ids, total = ApplyBeingInviterZset(user_id).get_item_ids(0, sys.maxint)
    else:
        phone_ids, total = [], 0

    infos = []
    count_coins = 0
    today_invite_good_num = 0
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    for fi_phone in phone_ids:
        phone_str = str(fi_phone)
        phone_small = "%s****%s" % (phone_str[:3], phone_str[-4:])
        phone_obj = HdBeingInviterCoins.fetch(fi_phone)
        if not phone_obj or (phone_obj.from_user_id != user_id) or (not phone_obj.regist and phone_obj.timeout):
            infos.append({
                'phone': phone_small,
                'success': 0,
                'msg': u"好友三天内未注册"
            })
        elif not phone_obj.regist:
            infos.append({
                'phone': phone_small,
                'success': 0,
                'msg': u"好友未注册"
            })
        elif not phone_obj.meet:
            infos.append({
                'phone': phone_small,
                'success': 0,
                'msg': u"好友不符合奖励规则"
            })
        elif phone_obj.processed == 0:
            infos.append({
                'phone': phone_small,
                'success': 0,
                'msg': u"正在结算中"
            })
        else:
            inviter_coins = BEINVITE_INVITE_COINS.get(phone_obj.coins, 0)
            count_coins += inviter_coins
            if phone_obj.regist_time.strftime("%Y-%m-%d") == today_str:
                today_invite_good_num += 1
            infos.append({
                'phone': phone_small,
                'success': 1,
                'be_inviter_coins': phone_obj.coins,
                'inviter_coins': inviter_coins
            })

    invite_phones = {
        'num': total,
        'count_coins': count_coins,
        'infos': infos
    }

    return dict_result({
        'available_flag': available_flag,
        'tips': tips,
        'user_id': user_id,
        'share_click_url': share_click_url,
        'invite_phones': invite_phones,
        'today_invite_good_num': today_invite_good_num,
        'today_invite_rank': today_invite_rank,
    })

@get('/activity/invitecoins/rank.js')
@jsonp
@check_login(False)
def invitecoins_rank():
    members = InviterRankZset.get_rank_members()
    return dict_result({
        'members': members,
    })


@get('/huodong/invitecoins/share/<user_id:int>.html')
@view('web/huodong/invitecoins/share')
def invitecoins_share_html(user_id):
    user = User.get(user_id or 0)
    allow_phone = 1
    error_tips = u""

    if not user:
        allow_phone = 0
        error_tips = u"邀请人信息有误,无法完成邀请"

    check_time = get_now_datetime()
    if check_time < INVITE_BEGIN_TIME:
        allow_phone = 0
        error_tips = u"活动未开始"
    elif check_time > INVITE_END_TIME:
        allow_phone = 0
        error_tips = u"活动已结束"

    request_url = request.url
    shareInfo = {
        'title': u"能不能领999枚金币就看你的颜值了！",
        'desc': u"速度来领，来不及多说了",
        'linkUrl': request_url,
        'imgUrl': 'http://static.itangyuan.com/activity/invitecoins.jpg',
    }
    user_info = user.dump_tag()
    if not user_info.get("avatar_url"):
        user_info["avatar_url"] = "http://static.itangyuan.com/activity/invitecoins.jpg"
    weixin_config = {}
    try:
        weixin_config = WeixinFacade.get_jssdk_config(request_url)
    except Exception,e:
        traceback.print_exc()
        print "weixin_config error:",e

    result = {
        'user': user_info,
        'allow_phone': allow_phone,
        'error_tips': error_tips,
        'weixin_config': weixin_config,
        'shareInfo': shareInfo,
    }
    return {'json_params': json.dumps(result)}


@post('/huodong/invitecoins/get_coins.json')
def invitecoins_get_coins():
    err_msg = ""
    phone = param('phone', 0, int)
    from_user_id = param('from_user_id', 0, int)
    user = User.get(from_user_id)
    if not user:
        err_msg = u"邀请链接失效"
        return Error(1, err_msg).dump()

    check_time = get_now_datetime()
    if check_time < INVITE_BEGIN_TIME:
        allow_phone = 0
        error_tips = u"活动未开始"
        return Error(1, error_tips).dump()
    elif check_time > INVITE_END_TIME:
        allow_phone = 0
        error_tips = u"活动已结束"
        return Error(1, error_tips).dump()

    msg, phone_obj = HdBeingInviterCoins.check_and_fetch(phone,
                                                         auto_create=True,
                                                         from_user_id=from_user_id)
    if msg:
        return Error(1, msg).dump()

    # 超时未注册 重新获取
    if not phone_obj.regist and phone_obj.timeout:
        phone_obj.from_user_id = from_user_id
        phone_obj.coins = get_be_inviter_random_coins()
        phone_obj.create_time = datetime.datetime.now()
        phone_obj.save()

    success_url = "http://%s/huodong/invitecoins/success/%s.html" % (DOMAIN, phone)
    return dict_result({
        'success_url': success_url
    })


@get('/huodong/invitecoins/success/<phone:int>.html')
@view('web/huodong/invitecoins/success')
def invitecoins_success_html(phone):
    phone_obj = HdBeingInviterCoins.fetch(phone)
    if not phone_obj:
        abort(404, 'Not Found')
    get_coins = phone_obj.coins
    phone_str = str(phone)
    phone_small = "%s****%s" % (phone_str[:3], phone_str[-4:])
    disable_time_str = phone_obj.disable_time_str

    result = {
        'get_coins': get_coins,
        'phone_small': phone_small,
        'disable_time_str': disable_time_str,
    }

    return result


"""
alter table manual_charge add column act_type int(10) unsigned NOT NULL DEFAULT  '0'  AFTER `operator_id`;
alter table manual_charge add column from_uid int(10) unsigned NOT NULL DEFAULT  '0'  AFTER `operator_id`;

CREATE TABLE `huodong_being_inviter_coins` (
`phone` varchar(12) CHARACTER SET utf8mb4 NOT NULL,
`user_id` int(10) unsigned NOT NULL,
`from_user_id` int(10) unsigned NOT NULL,
`coins` int(10) unsigned NOT NULL,
`status` tinyint(3) unsigned NOT NULL DEFAULT  '0',
`device_id` varchar(100) CHARACTER SET utf8mb4 DEFAULT NULL,
`create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
`regist_time` timestamp NOT NULL DEFAULT '0000-00-00 00:00:00',
`remote_addr` varchar(20) COLLATE utf8mb4_bin DEFAULT '',
`processed` tinyint(3) unsigned NOT NULL DEFAULT '0',
 PRIMARY KEY (`phone`),
 KEY device_id(`device_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE `huodong_inviter_coins` (
`id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
`user_id` int(10) unsigned NOT NULL,
`new_user_id` int(10) unsigned NOT NULL,
`coins` int(10) unsigned NOT NULL,
`create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
`processed` tinyint(3) unsigned NOT NULL DEFAULT '0',
 PRIMARY KEY (`id`),
 UNIQUE KEY `invite_new_user_id` (`new_user_id`),
 KEY user(`user_id`, `new_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
"""
