#!/usr/bin/env python
# coding=utf-8
import sys

reload(sys)
sys.setdefaultencoding("utf-8")
import os
import re

sys.path.insert(0, '/opt/itangyuan/itangyuan.com')
EVVIRONMENT_VARIABLE = 'RICEBALL_CONFIG_FILE'
env = 'local'
os.environ[
    EVVIRONMENT_VARIABLE] = '/opt/itangyuan/itangyuan.com/conf/%s/settings.conf' % env

from riceball.storage.client import redis, mysql

# 索引文件名
treeXmlFile = 'sitemap.xml'

# 搜索数据数量限制参数
sql_count = 500

# 数据条数限制
sitemapCount = 49000

# 文件个数上限
fileLimitCount = 1000

# 更新频率
frequency = ("always", "hourly", "daily", "weekly", "monthly", "yearly")


##############    脚本运行参数设置
folder = ['agree_book', 'normal_book']
filepre = ['agree', 'normal']
urlLen = 300
fileCounts = 500
freq = frequency[3]



# sitemap模板
'''
changefreq:页面内容更新频率。
lastmod:页面最后修改时间
loc:页面永久链接地址
priority:相对于其他页面的优先权
url:相对于前4个标签的父标签
urlset:相对于前5个标签的父标签

获取数据，并将数据转换为url格式数据

数据进行xml格式拼接

数据写入文件，记录数据条数，生成xml文件，记录文件个数，并保存xml文件名到fileList中

读取fileList文件名数据，生成sitemapTree.xml文件

'''


class XmlTree():
    def __init__(self, treeXmlFile):
        # 内容结构
        self.tplTreeTop = '<?xml version="1.0" encoding="utf-8"?>\n'
        self.sitemapindexBegin = '<sitemapindex>\n'
        self.tplTreeContent = '<loc>%s</loc>\n'
        self.sitemapindexEnd = '</sitemapindex>'
        self.sitemap = '<sitemap>\n%s</stiemap>'

        self.filename = treeXmlFile
        self.file = open(self.filename, 'a+')
        self.file.write(self.tplTreeTop)
        self.file.write(self.sitemapindexBegin)
        # xml索引
        self.tree_xml_url = 'http://www.itangyuan.com/sitemap/%s'
    def fileInsert(self, date):
        date = self.tree_xml_url % date
        temp = self.tplTreeContent % date
        self.file.write(self.sitemap % temp)

    def fileClose(self):
        self.file.write(self.sitemapindexEnd)
        self.file.close()


# a = xmlTree(treeXmlFile)
# a.fileInsert('123456')
# a.fileClose()

class XmlFile():
    def __init__(self, folder, filepre, urlLen, fileCounts, freq):
        self.tpl = '<?xml version="1.0" encoding="utf-8"?>\n'
        self.urlsetBegin = '<urlset>\n'
        self.urlsetEnd = '</urlset>'
        self.url = '<url>\n%s</url>'
        self.loc = '<loc>%s</loc>\n'
        self.changefreq = '<changefreq>%s</changefreq>\n'
        self.setFolder(folder)
        self.filepre = filepre
        self.urlLen = urlLen
        self.urlCount = 1
        self.fileCounts = fileCounts
        self.fileCount = 1
        self.freq = freq
        self.step = 0
        self.filename = ''
        self.suffix = '.xml'
        self.date = ''
        self.filesname = []
        self.file = file

    def getStep(self):
        return self.step

    def setStep(self, step):
        self.step = step

    def setFolder(self, folder):
        self.folder = folder
        self.judgeFolder(folder)

    def getFileName(self):
        return self.filepre[self.step] + '-' + str(self.fileCount) + self.suffix

    def createFile(self):
        self.urlCount = 1
        self.path = self.folder[self.step] + '/' + self.getFileName()
        self.filesname.append(self.path)
        self.file = open(self.path, 'w')
        self.file.write(self.tpl + self.urlsetBegin)
        print 'createFile ', self.path

    def dateInsert(self, date):
        self.date = date
        loc = self.loc % self.date
        changefreq = self.changefreq % self.freq
        url = loc + changefreq
        self.file.write(self.url % url)
        self.urlCount += 1

    def getUrlCount(self):
        return self.urlCount

    def loop(self, date):
        if not self.date:
            self.date = date
        if self.urlCount == 1:
            self.createFile()
        if self.urlCount < self.urlLen:
            self.dateInsert()
            self.date = None
        else:
            self.filesname.append(self.path)
            self.closeFile()
            if self.date:
                date = self.date
                self.loop(date)

    def closeFile(self):
        self.file.write(self.urlsetEnd)
        self.file.close()
        self.fileCount += 1
        self.urlCount = 1
        print 'closeFile ', self.path

    def judgeFolder(self, folder):
        for d in folder:
            if not os.path.exists(d):
                os.mkdir(d)


class DateUrl():
    def __init__(self):
        self.offset = sql_count
        self.count = 0
        self.choffset = sql_count
        self.chcount = 0
        self.book_ids_url = 'http://www.itangyuan.com/book/%s.html'  # 书籍url模版
        self.book_catalogue_url = 'http://www.itangyuan.com/book/catalogue/%s.html'  # 目录url模版
        self.book_chapter_url = 'http://www.itangyuan.com/book/chapter/%s/%s.html'  # 章节url模版
        self.select_count = "select count(%s) from %s where %s;"
        self.sign_config = '(word_count > 1000) and (deleted = 0) and (status & 0x00000008 > 0) and (sign_status > 0)'
        self.unsign_config = '(word_count > 1000) and (deleted = 0) and (status & 0x00000008 > 0) and (sign_status <= 0)'
        self.select_sql = "select %s from %s where %s %s"
        self.chapter_config = '(status & 0x00000004 > 0) and (book_id = %d)'

    def limitCount(self):
        self.count += self.offset

    def limit(self):
        print 'count ', self.count, 'offset ', self.offset
        return 'limit %d, %d' % (self.count, self.offset)

    def chlimitCount(self):
        self.chcount += self.choffset

    def resetChCount(self):
        self.chcount = 0

    def resetCount(self):
        self.count = 0

    def chlimit(self):
        return 'limit %d, %d' % (self.chcount, self.choffset)

    def getIdsUrl(self, id):
        return self.book_ids_url % id

    def getCatalogueUrl(self, id):
        return self.book_catalogue_url % id

    def getChapterUrl(self, IdBook, id):
        return self.book_chapter_url % (IdBook, id)

    def listToUse(self, date):
        return date[0].values()[0]

    def dateToUse(self, date):
        return date.values()[0]

    def searchContent(self, key, table, config, limit):
        return mysql.query(self.select_sql % (key, table, config, limit))

    def searchCount(self, key, table, config):
        return mysql.query(self.select_count % (key, table, config))


sqldate = DateUrl()
unsqldate = DateUrl()
xfile = XmlFile(folder, filepre, urlLen, fileCounts, freq)
xtree = XmlTree(treeXmlFile)


def filerun(date):
    if xfile.filesname:
        xtree.fileInsert(xfile.filesname[0])
        print 'xfile.filesname ', xfile.filesname[0]
        del xfile.filesname[0]

    if xfile.urlCount > xfile.urlLen - 1:
        if not xfile.file.closed:
            xfile.closeFile()
        if xfile.file.closed and xfile.fileCount <= xfile.fileCounts:
            print 'xfile.fileCounts 111 ', xfile.fileCounts, xfile.fileCount
            xfile.createFile()

    if xfile.fileCount > xfile.fileCounts:
        if not xfile.file.closed:
            xfile.closeFile()
        return False
    try:
        xfile.dateInsert(date)
        return True
    except:
        return False


def signloop(key, table):
    print 'xfile.fileCounts 0 ', xfile.fileCounts, xfile.fileCount
    if xfile.file.closed and xfile.fileCount <= xfile.fileCounts:
        print 'xfile.fileCounts 111111 ', xfile.fileCounts, xfile.fileCount
        xfile.createFile()
    count_all = sqldate.searchCount(key[0], table[0], sqldate.sign_config)
    count_all = sqldate.listToUse(count_all)
    loop = count_all / sqldate.offset + 1

    while (loop > 0):
        print 'xfile.fileCounts 1 ', xfile.fileCounts, xfile.fileCount
        if xfile.fileCount > xfile.fileCounts:
            break
        limit = sqldate.limit()
        list = sqldate.searchContent(key[0], table[0], sqldate.sign_config, limit)

        for temp in list:
            sqldate.resetChCount()
            if not filerun(sqldate.getIdsUrl(sqldate.dateToUse(temp))):
                 break
            if not filerun(sqldate.getCatalogueUrl(sqldate.dateToUse(temp))):
                break

            count_allch = sqldate.searchCount(key[1], table[1], sqldate.chapter_config % sqldate.dateToUse(temp))
            print 'count_allch', count_allch
            count_allch = sqldate.listToUse(count_allch)
            ch_loop = count_allch / sqldate.choffset + 1
            print 'ch_loop', ch_loop

            while (ch_loop > 0):
                print 'while ch_loop ', ch_loop
                print 'xfile.fileCounts 2 ', xfile.fileCounts, xfile.fileCount
                if xfile.fileCount > xfile.fileCounts:
                    break
                ch_limit = sqldate.chlimit()
                chlist = sqldate.searchContent(key[1], table[1], sqldate.chapter_config % sqldate.dateToUse(temp), ch_limit)
                print 'chilist ', chlist

                for chtemp in chlist:
                    if not filerun(sqldate.getChapterUrl(sqldate.dateToUse(temp), sqldate.dateToUse(chtemp))):
                        break
                sqldate.chlimitCount()
                ch_loop -= 1
                print '----ch_loop', ch_loop

        sqldate.limitCount()
        loop -= 1

    if not xfile.file.closed:
        xfile.closeFile()
    
    print 'xfile.fileCounts 3 ', xfile.fileCounts, xfile.fileCount
    
    #if xfile.fileCounts > xfile.fileCount:
    xfile.fileCounts -= xfile.fileCount - 1
    xfile.fileCount = 1
    print 'xfile.fileCounts 4 ', xfile.fileCounts, xfile.fileCount


def unsignloop(key, table):
    xfile.setStep(1)
    if xfile.file.closed and xfile.fileCount <= xfile.fileCounts:
        xfile.createFile()
    count_all = unsqldate.searchCount(key, table, unsqldate.unsign_config)
    count_all = sqldate.listToUse(count_all)
    loop = count_all / unsqldate.offset + 1

    while (loop):
        if xfile.fileCount > xfile.fileCounts:
            break
        limit = unsqldate.limit()
        list = unsqldate.searchContent(key, table, unsqldate.unsign_config, limit)

        for temp in list:
            if not filerun(unsqldate.getIdsUrl(unsqldate.dateToUse(temp))):
                break
            if not filerun(unsqldate.getCatalogueUrl(unsqldate.dateToUse(temp))):
                break

        unsqldate.limitCount()
        loop -= 1

    if not xfile.file.closed:
        xfile.closeFile()
    #if xfile.fileCounts > xfile.fileCount:
    xfile.fileCounts -= xfile.fileCount - 1
    xfile.fileCount = 1

key = ['id', 'id']
table = ['book', 'chapter']
signloop(key, table)
unsignloop(key[0], table[0])

