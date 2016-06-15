# -*- coding: utf-8 -*-

import sys
reload(sys)
sys.setdefaultencoding("utf-8")
import os
import sys
import datetime
import re

sys.path.insert(0, '/opt/itangyuan/itangyuan.com')
ENVIRONMENT_VARIABLE = 'RICEBALL_CONFIG_FILE'
env = 'local'

os.environ[
    ENVIRONMENT_VARIABLE] = '/opt/itangyuan/itangyuan.com/conf/%s/settings.conf' % env

from ricebag.model.book import Book

import time
import traceback
from collections import OrderedDict

from bottle import request

from ricebag.conf import common as common_config
from ricebag.model.chapter import Chapter
from ricebag.model.comment import Comment, BookCommentZSet, BookCommentHeatZSet
from ricebag.tools import find_informal_name_part
from ricebag.tools.file import FileObject, PublicFileKeyTemplateConst, \
    QiniuPublicFileProcessor
from ricebag.tools.qetag import get_data_qetag
from ricebag.typ import redirect_typ_pool
from riceball.options import settings
from riceball.storage import storage
from riceball.storage.client import mysql, redis, SQLErrorCode, SQLError
from riceball.storage.model import ModelObject, ModelViewList, ModelSortedSet, \
    Counter, Rank
from riceball.storage.xmodel import XModelObject, model_config, xfield
from riceball.storage.xmodel.engine import CachedEngine
from riceball.tools import text, cached
from riceball.tools.image import ImageUtil


import pdb


__author__ = 'ocean'

FULLUPDATEDAY = 1073741823
FULLDAYS = 30


print 'program start'

# 排行榜表类
@storage()
class Charts(XModelObject):
    """
    :var update_status: 30天更新状态,二进制数
    :var update_status: 书籍签约状态
    :var updateDay: 30天内更新天数
    :var updateFreq: 书籍更新频率
    :var serialUpdate: 书籍连更天数
    :var lastUpdateTime: 书籍最新更新时间
    :var govTag: 官方标签
    :var tag: 标签
    :var deleted: 标签
    """
    model_config = model_config('id', auto_creatable=True)
    model_engine = CachedEngine.mysql_object(table='charts')

    id = xfield.int(None)
    update_status = xfield.int(None)
    updateDay = xfield.int(None)
    updateFreq = xfield.float(None)
    serialUpdate = xfield.int(None)
    lastUpdateTime = xfield.datetime(datetime.datetime.now)
    govTag = xfield.int(None)
    tag = xfield.int(None)
    deleted = xfield.int(None)


    def add_update_day(self):
        # 有更新,更新天数变化
        if self.updateDay <= FULLUPDATEDAY:
            self.updateDay = (self.updateDay << 1) + 1
            #提交更新
            self.save()


    def update_day_update(self):
        # 没有更新,更新天数变化
        #self.updateDay = self.updateDay << 1
        if self.updateDay <= FULLUPDATEDAY:
            self.updateDay <<= 1
            #提交更新
            self.save()


    def get_update_day(self):
        # 获取更新天数
        temp = self.updateDay
        count = 0
        while temp:
            if temp & 1:
                count += 1
            temp >>= 1

        return count


    def freq_update(self):
        # 刷新更新频率
        if self.updateFreq <= 1:
            self.updateFreq = float(self.get_update_day()) / FULLDAYS
            #提交更新
            self.save()


    def serial_update(self, chapter):
        # 连续更新处理
        if chapter.publish_time.day - self.lastUpdateTime.day <= 1 and chapter.publish_time.day - self.lastUpdateTime.day >= 0:
            self.serialUpdate += 1
        elif chapter.publish_time.day - self.lastUpdateTime.day > 1:
            self.serialUpdate = 0
        #提交更新
        self.save()

    @classmethod
    def book_ids_list(cls):
        # 获取更新表中所有书籍id
        sql = 'SELECT id FROM charts'
        return [i.values()[0] for i in mysql.query(sql)]


#test
#chart = Charts.fetch(6342)
#print chart.lastUpdateTime

#print chart.updateDay
#print 'chart.updateDay', chart.get_update_day()
#chart.freq_update()
#print chart.updateFreq
#print 'chart.id', chart.id
#chapter = Chapter.get(Book.get(chart.id).last_chapter_id)
#print chapter.id
#print 'chart.lastUpdateTime', chart.lastUpdateTime
#chart.serial_update(chapter)
#print 'chart.serialUpdate', chart.serialUpdate


# 通过推送消息,获取书籍对象和章节对象
def get_date_from_catch(msg):
    chapter_id = int(msg)
    chapter = Chapter.get(chapter_id)

    def getBookInfo():
        book_info = chapter.book if chapter else None
        return book_info

    def getChapterInfo():
        return chapter

    return getBookInfo(), getChapterInfo()

msg = 70348
#print 'get_date_from_catch()', get_date_from_catch(msg)

# 订阅章节更新,发生更新时,排行榜表进行数据处理
def sigleUpdate(book_id, newChapter_id):
    book, chapter = get_date_from_catch(newChapter_id)

    chart = Charts.fetch(book.id)
    #pdb.set_trace()
    # 非签约书籍,变为签约
    if book.sign_status != chart.update_status:
        chart.update_status = book.sign_status

    # 更新天数增加1
    # 判断更新未满30天
    if chart.updateDay < FULLUPDATEDAY:
        chart.add_update_day()
        chart.freq_update()

    # 处理连更天数
    chart.serial_update(chapter)

    # 刷新最后更新时间, 最后刷新时间就是新章节的发布时间
    # 最后刷新时间就是程序运行当前时间，如果章节更是时间为当日时间，最后更新时间就是最新章节发布时间
    # pdb.set_trace()
    type(chapter.publish_time)
    if chapter.publish_time.day == datetime.datetime.now().day:
        chart.lastUpdateTime = chapter.publish_time
    else:
        chart.lastUpdateTime = datetime.datetime.now()
    chart.save()

#sigleUpdate(6342, msg)



# 获取book的章节列表
def getChapters(book):
    count = book.published_chapter_count
    chapter_list = book.published_chapter_ids.range(0, count - 1)
    return count, chapter_list


# 判断最后更新时间和章节发布时间
def judgeTime(last, chaTime):
    '''
#    :param last: 书籍最后更新时间
#    :param chaTime: 章节发布时间
#    :return:    1 '时间一致"相等"'
#                2 '章节发布时间大于最后更新时间'
#                3 '章节发布时间超出更新范围'
#                4 '章节发布时间与最后更新时间在'小时\分\秒'判断时小于最后更新时间'
    '''
    if last == chaTime:
        return 1
    else:
        if chaTime.year == last.year:
            if chaTime.month == last.month:
                if chaTime.day == last.day:
                    if chaTime.hour == last.hour:
                        if chaTime.minute == last.minute:
                            if chaTime.second > last.second:
                                return 2
                            if chaTime.second < last.second:
                                return 4
                        else:
                            if chaTime.minute > last.minute:
                                return 2
                            if chaTime.minute < last.minute:
                                return 4
                    else:
                        if chaTime.hour > last.hour:
                            return 2
                        if chaTime.hour < last.hour:
                            return 4
                else:
                    if chaTime.day > last.day:
                        if chaTime.day - last.day <= 1:
                            return 2
                        if chaTime.day - last.day > 1:
                            return 3
                    if chaTime.day < last.day:
                        return 4
            else:
                return 3
        else:
            return 3


# 更新排行榜表中所有时间相关信息
def allUpdate():
    # 获取排行榜表中所有书籍id
    list = Charts.book_ids_list()
    pdb.set_trace()
    # 遍历排行榜表中书籍,匹配更新时间
    for tempBookInfoLocal in list:
        print 'log start'
        book = Book.get(tempBookInfoLocal)
        count, chapter_list = getChapters(book)
        tempBookInfoLocal = Charts.fetch(tempBookInfoLocal)

        # 非签约书籍,变为签约
        if tempBookInfoLocal.update_status != book.sign_status:
            tempBookInfoLocal.update_status = book.sign_status

        loop_count = 0
        # 判断章节id的发布时间与排行榜中最后更新时间
        for chapter in chapter_list:
            temp = Chapter.get(chapter)

            # 有连续更新
            if judgeTime(tempBookInfoLocal.lastUpdateTime, temp.publish_time) == 2:
                tempBookInfoLocal.serialUpdate += 1
                pdb.set_trace()

                # 更新天数增加1
                # 判断更新未满30天
                if tempBookInfoLocal.updateDay < FULLUPDATEDAY:
                    tempBookInfoLocal.add_update_day()
                    tempBookInfoLocal.freq_update()

                # 刷新最后更新时间, 最后刷新时间就是新章节的发布时间
                tempBookInfoLocal.lastUpdateTime = temp.publish_time
                tempBookInfoLocal.save()

            # 无更新
            if judgeTime(tempBookInfoLocal.lastUpdateTime, temp.publish_time) == 3:
                if loop_count == 0:
                    tempBookInfoLocal.serialUpdate = 0
                    tempBookInfoLocal.save()

                print 'log updateDay'
                # 更新天数刷新
                # 判断更新未满30天
                if tempBookInfoLocal.updateDay < FULLUPDATEDAY:
                    tempBookInfoLocal.update_day_update()
                    tempBookInfoLocal.freq_update()
                break
            loop_count += 1


#allUpdate()
#chart = Charts.fetch(6342)

#print chart.get_update_day()
#chart.freq_update()
#print chart.updateFreq
