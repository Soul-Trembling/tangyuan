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

# from riceball.storage.client import redis, mysql

urlCounts = 0
fileCounts = 0

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

# sitemap模板
'''
changefreq:页面内容更新频率。
lastmod:页面最后修改时间
loc:页面永久链接地址
priority:相对于其他页面的优先权
url:相对于前4个标签的父标签
urlset:相对于前5个标签的父标签

'''
tpl = '<?xml version="1.0" encoding="utf-8"?>\n'
urlsetBegin = '<urlset>\n'
urlsetEnd = '</urlset>'
url = '<url>\n%s</url>'
loc = '<loc>%s</loc>\n'
changefreq = '<changefreq>%s</changefreq>\n'
urlset = '<urlset>\n<url>\n<loc>%s</loc>\n<changefreq>weekly</changefreq>\n</url>\n</urlset>'

tplTreeTop = '<?xml version="1.0" encoding="utf-8"?>\n'
sitemapindexBegin = '<sitemapindex>\n'
tplTreeContent = ''
sitemapindexEnd = '</sitemapindex>'
sitemap = '<sitemap>\n%s</stiemap>'

# url模版
book_ids_url = 'http://www.itangyuan.com/book/%s.html'  # 书籍url模版
book_catalogue_url = 'http://www.itangyuan.com/book/catalogue/%s.html'  # 目录url模版
book_chapter_url = 'http://www.itangyuan.com/book/chapter/%s/%s.html'  # 章节url模版

# xml索引
tree_xml_url = 'http://www.itangyuan.com/sitemap/%s.xml'

'''
获取数据，并将数据转换为url格式数据

数据进行xml格式拼接

数据写入文件，记录数据条数，生成xml文件，记录文件个数，并保存xml文件名到fileList中

读取fileList文件名数据，生成sitemapTree.xml文件

'''


class XmlTree():

    def __init__(self, treeXmlFile):
        self.filename = treeXmlFile
        self.file = open(self.filename, 'a+')
        self.file.write(self.tplTreeTop)
        self.file.write(sitemapindexBegin)
        # xml索引
        self.tree_xml_url = 'http://www.itangyuan.com/sitemap/%s'
        # 内容结构
        self.tplTreeTop = '<?xml version="1.0" encoding="utf-8"?>\n'
        self.sitemapindexBegin = '<sitemapindex>\n'
        self.tplTreeContent = '<loc>%s</loc>\n'
        self.sitemapindexEnd = '</sitemapindex>'
        self.sitemap = '<sitemap>\n%s</stiemap>'

    def fileInsert(self, date):
        date = tree_xml_url % date
        temp = self.tplTreeContent % date
        self.file.write(sitemap % temp)

    def fileClose(self):
        self.file.write(sitemapindexEnd)
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
        self.file = open(self.path, 'w')
        self.file.write(self.tpl + self.urlsetBegin)
        print 'createFile'

    def dateInsert(self):
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
        print '!!!!!!!!!'

    def closeFile(self):
        self.file.write(self.urlsetEnd)
        self.file.close()
        self.fileCount += 1
        self.urlCount = 1
        print 'closeFile'

    def judgeFolder(self, folder):
        for d in folder:
            if not os.path.exists(d):
                os.mkdir(d)


class DateUrl():
    book_ids_url = 'http://www.itangyuan.com/book/%s.html'  # 书籍url模版
    book_catalogue_url = 'http://www.itangyuan.com/book/catalogue/%s.html'  # 目录url模版
    book_chapter_url = 'http://www.itangyuan.com/book/chapter/%s/%s.html'  # 章节url模版

    select_count = "select count(%s) from %s where %s;"

    sign_config = '(word_count > 1000) and (deleted = 0) and (status & 0x00000008 > 0) and (sign_status > 0)'
    unsign_config = '(word_count > 1000) and (deleted = 0) and (status & 0x00000008 > 0) and (sign_status <= 0)'

    select_sql = "select %s from %s where %s %s"

    chapter_config = '(status & 0x00000004 > 0) and (book_id = %d)'

    def __init__(self):
        self.offset = sql_count
        self.count = 0

        self.choffset = sql_count
        self.chcount = 0

    def limitCount(self):
        self.count += self.offset

    def limit(self):
        return 'limit %d, %d' % (self.count, self.offset)

    def chlimitCount(self):
        self.chcount += self.choffset

    def chlimit(self):
        return 'limit %d, %d' % (self.chcount, self.choffset)

    def getIdsUrl(self, id):
        return book_ids_url % id

    def getCatalogueUrl(self, id):
        return book_catalogue_url % id

    def getChapterUrl(self, id):
        return book_chapter_url % id

    def dateToUse(self, date):
        return date[0].values()[0]

    def searchContent(self, key, table, config, limit):
        return mysql.query(self.select_sql % (key, table, config, limit))

    def searchCount(self, key, table, config):
        return mysql.query(self.select_count % (key, table, config))


class ControlPro():
    def __init__(self, treeXmlFile, folder, filepre, urlLen, fileCounts, freq):
        self.c_treeXmlFile = treeXmlFile
        self.c_folder = folder
        self.c_filepre = filepre
        self.c_urlLen = urlLen
        self.c_fileCounts = fileCounts
        self.c_freq = freq

        self.xmlTree = XmlTree(self.c_treeXmlFile)
        self.xmlFile = XmlFile(self.c_folder, self.c_filepre, self.c_urlLen, self.c_fileCounts, self.c_freq)
        self.dateUrl = DateUrl()


    def loopMain(self, key, table):

        self.c_count = self.dateUrl.searchCount(key, table, self.dateUrl.sign_config)
        self.c_loop = self.c_count / self.dateUrl.offset + 1

        while self.c_loop:
            limit = self.dateUrl.limit()
            sqlBookContentList = self.dateUrl.searchContent(key, table, self.dateUrl.sign_config, limit)
            self.dateUrl.limitCount()
            for date in sqlBookContentList:
                date = self.dateUrl.dateToUse(date)
                url = self.dateUrl.getIdsUrl(date)
                urlCatalogue = self.dateUrl.getCatalogueUrl(date)

                if self.xmlFile.fileCount > self.xmlFile.fileCounts - 1:
                    break

                if self.xmlFile.fileCount < self.xmlFile.fileCounts:
                    # if not self.xmlFile.getStep():
                    #     self.xmlFile.setStep(1)
                    self.xmlFile.loop(url)
                    self.xmlFile.loop(urlCatalogue)
                    self.loopChapter('id', 'chapter', date)
                    # chlimit = self.dateUrl.chlimit()
                    # sqlChapterContentList = self.dateUrl.searchContent(key, table, self.dateUrl.chapter_config, chlimit)
                    # self.dateUrl.chlimitCount()

    def loopChapter(self, key, table, bookId):
        self.ch_count = self.dateUrl.searchCount(key, table, self.dateUrl.chapter_config % bookId)
        self.ch_loop = self.ch_count / self.dateUrl.choffset + 1

        while self.ch_loop:
            chlimit = self.dateUrl.chlimit()
            sqlChapterContentList = self.dateUrl.searchContent(key, table, self.dateUrl.chapter_config % bookId, chlimit)
            self.dateUrl.chlimitCount()
            for date in sqlChapterContentList:
                date = self.dateUrl.dateToUse(date)
                url = self.dateUrl.getChapterUrl(date)

                if self.xmlFile.fileCount > self.xmlFile.fileCounts - 1:
                    break

                if self.xmlFile.fileCount < self.xmlFile.fileCounts:
                    # if not self.xmlFile.getStep():
                    #     self.xmlFile.setStep(1)
                    self.xmlFile.loop(url)

    def unLoopMain(self, key, table):
        self.xmlFile.setStep(1)
        self.c_count = self.dateUrl.searchCount(key, table, self.dateUrl.unsign_config)
        self.c_loop = self.c_count / self.dateUrl.offset + 1

        while self.c_loop:
            limit = self.dateUrl.limit()
            sqlBookContentList = self.dateUrl.searchContent(key, table, self.dateUrl.unsign_config, limit)
            self.dateUrl.limitCount()
            for date in sqlBookContentList:
                date = self.dateUrl.dateToUse(date)
                url = self.dateUrl.getIdsUrl(date)
                urlCatalogue = self.dateUrl.getCatalogueUrl(date)

                if self.xmlFile.fileCount > self.xmlFile.fileCounts - 1:
                    break

                if self.xmlFile.fileCount < self.xmlFile.fileCounts:
                    # if not self.xmlFile.getStep():
                    #     self.xmlFile.setStep(1)
                    self.xmlFile.loop(url)
                    self.xmlFile.loop(urlCatalogue)

    def createTree(self):
        while self.xmlFile.filesname[0]:
            self.xmlTree.fileInsert(self.xmlFile.filesname[0])
            del self.xmlFile.filesname[0]

        self.xmlTree.fileClose()



folder = ['agree_book', 'normal_book']
filepre = ['agree', 'normal']
urlLen = 3
fileCounts = 7
freq = frequency[3]
agreeCount = 4

con = ControlPro(treeXmlFile, folder, filepre, urlLen, fileCounts, freq)
con.loopMain('id', 'book')
con.unLoopMain('id', 'book')
con.createTree()


# folder = ['agree_book', 'normal_book']
# filepre = ['agree', 'normal']
# urlen = 3
# fileCounts = 7
# freq = frequency[3]
# b = xmlFile(folder, filepre, urlen, fileCounts, freq)
# date = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 9, 10, 11, 12)
# agreeCount = 4
#
# for i in date:
#     if b.fileCount > fileCounts - 1:
#         break
#
#     if b.fileCount < b.fileCounts:
#         if not b.getStep() and b.fileCount > agreeCount:
#             b.setStep(1)
#         b.loop(i)
