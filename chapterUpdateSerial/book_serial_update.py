# -*- coding: utf-8 -*-
__author__ = 'donlon'

# 基础数据
signBookUpdateLevel = {0, 3, 7, 15, 30}

bookInfo = {
    'bookId': bookId,
    'bookName' : bookName,
    'author' : author,
    'attribute' : attribute,
    'label' : label,
    'dataCount' : dataCount,
    'time' : time,
    'control' : control,
    'UpdateDays' : UpdateDays
}


# 数据查询
def getSignBookIds():
    return book_ids


# 通过天数获取符合条件的book_id
def getUpdateSerial(book_ids):
    pass


# 保存数据到ssdb
def saveDataToSsdb(data):
    pass


# 从ssdb中拿数据
def dataFromSsdb():
    pass

# url调用,数据回馈
def urlCathData():
    pass


# 主处理函数
def bookSerialUpdate(day_count):
    # 获得签约书籍id
    book_ids = getSignBookIds()
    # 通过id获取签约书籍信息
    book_info = getUpdateSerial(book_ids)
    # 将信息存储到Ssdb
    saveDataToSsdb(book_info)
    # 从Ssdb上获取签约书籍信息
    info_book = dataFromSsdb()



# 网页数据呈现




