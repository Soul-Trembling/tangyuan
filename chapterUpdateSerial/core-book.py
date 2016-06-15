# -*- coding: utf-8 -*-

import datetime
import re
import ujson as json

from bottle import get, post, request
from application.action.manage import gen_path_func, set_response, widget_result
from application.action.manage.association import manage_operation_log
from application.action.manage.webutils.layout import \
    widget_dialog_layout_processor
from application.tools import send_sensitive_mail
from ricebag import param, pagelet, dict_result
from ricebag.conf import error
from ricebag.error import Error
from ricebag.logic import booklogic, comment_logic
from ricebag.logic.booklogic import ChapterContentUtil
from ricebag.model import badwords
from ricebag.model.book import Book, TopBook, BookShareRecord
from ricebag.model.chapter import Chapter
from ricebag.model.comment import Comment
from ricebag.model.manage import ManageBook, ManageOperationLog, \
    ManageTempFile, ManageUser, ManageChapter, ManageBookGiftCount, \
    ManageBookContributorGiftCount
from ricebag.model.notice import Notice
from ricebag.model.puppet import ManagerPuppets, LastUsedPuppet
from ricebag.model.reward import BookRewardCount, BookContributorsZSet
from ricebag.model.tag import Tag
from ricebag.model.user import User
from ricebag.tools.push import Push
from ricebag.typ import redirect_typ_pool as typ
from riceball.tools import fx
from riceball.tools.image import ImageUtil
from riceball.tools.number import toint
from riceball.tools.text import tobytes, tounicode, format_comment, \
    char_count_ty, display_length
from ricebag.searchmodel.distributionchannel import DistributionChannelSearcher
from ricebag.searchmodel.book import BookSearcher
from ricebag.searchmodel import SearchUpdateNotification

# ------ serial新增
from riceball.storage.xmodel.charts import Charts

__author__ = 'eisen'

request_path, tpl_path = gen_path_func('/core/book')


# ====================后台章节预览开始====================

@get(request_path('/read/<book_id:int>.html'))
@set_response(tpl_path('/read'), layout_processor=None)
def book_read_html(book_id):
    book = Book.get(book_id)
    return {'json_params': json.dumps({
        'book_id': book.id if book else None
    })}


@get(request_path('/read/<book_id:int>.json'))
@set_response()
def book_read_json(book_id):
    book = Book.get(book_id)

    if book is None:
        return error.data.BookNotFound.dump()

    chapter_ids = book.published_chapter_ids[:]
    chapter_dict = Chapter.gets(*chapter_ids)
    chapters = [chapter_dict.get(fi_cid).dump_detail() for fi_cid in chapter_ids
                if chapter_dict.get(fi_cid)]

    return dict_result({
        'book': book.dump_detail(),
        'chapters': chapters
    })


@get(request_path('/read/chapter/<book_id:int>/<chapter_id:int>.html'))
@set_response(None, require_login=True, load_page_js=False,
              layout_processor=None)
def book_read_chapter_content(book_id, chapter_id):
    """
    查看公开章节的已发布内容
    :param book_id:
    :param chapter_id:
    :return:
    """
    chapter = Chapter.get(chapter_id)
    if chapter is None or not chapter.published \
            or chapter.book is None or chapter.book.id != book_id:
        content = u'您要访问的章节不存在或已被原作者删除。'
    else:
        content = ChapterContentUtil.render_pretty_chapter_body_inner_content(chapter, secure=True)
    return u'<div>%s</div>' % content


@get(request_path('/read/chapter/auditing/<book_id:int>/<chapter_id:int>.html'))
@set_response(None, require_login=True, load_page_js=False,
              layout_processor=None)
def read_auditing_chapter(book_id, chapter_id):
    """
    查看正在被审核的章节内容
    :param book_id:
    :param chapter_id:
    :return:
    """
    chapter = Chapter.get(chapter_id)
    manage_chapter = ManageChapter.get(chapter_id)
    if chapter is None or not chapter.published \
            or chapter.book is None or chapter.book.id != book_id:
        content = u'您要访问的章节不存在或已被原作者删除。'
    else:
        if not manage_chapter:
            content = u'当前章节不在审核状态。'
        else:
            content = ChapterContentUtil.render_pretty_auditing_chapter_body_inner_content(chapter)

    def highlight(match):
        return u'<a style="color:red; font-size: 24px" href="javascript:;">%s</a>' % match.group(0)

    content = badwords.chapter.regex.sub(highlight, content)
    return u'<html><body><div>%s</div></body></html>' % content


@get(request_path('/read/comment/add.html'))
@set_response(tpl_path('/comment_add'),
              layout_processor=widget_dialog_layout_processor)
def book_read_comment_add():
    book_id = param('book_id', 0, int)
    chapter_id = param('chapter_id', 0, int)

    result = widget_result('widget_comment_add', u'发表评论')

    book = Book.get(book_id)
    if book is None:
        return result.set_param({'error': u'该书不存在'}).dump()

    chapter = None
    if chapter_id != 0:
        chapter = Chapter.get(chapter_id)
        if chapter is None:
            return result.set_param({'error': u'章节不存在'}).dump()
        if chapter.book_id != book.id:
            return result.set_param({'error': u'章节信息错误'}).dump()

    manager_id = request.uid
    puppets = ManagerPuppets.get(manager_id)

    if puppets is None:
        return result.set_param({'error': u'你无权限发表评论，请联系管理员'}).dump()

    user_ids = puppets[:]
    user_dict = User.gets(*user_ids)
    users = [user_dict[fi_uid].dumps('nickname') for fi_uid in user_ids
             if user_dict.get(fi_uid)]

    # 最后用过的马甲
    last_used_puppet = LastUsedPuppet.get(manager_id)

    return result.set_param({
        'book': book.dumps('name'),
        'chapter': chapter.dumps('title') if chapter is not None else None,
        'users': users,
        'last_used_puppet': last_used_puppet.user_id
    }).dump()


@post(request_path('/read/comment/post.json'))
@set_response()
def book_read_comment_post_json():
    book_id = param('book_id', 0, int)
    chapter_id = param('chapter_id', 0, int)
    user_id = param('user_id', 0, int)
    content = param('content', '', tounicode)

    #
    if content is None:
        return error.request.ParamEmpty.dump(param=u'评论内容')
    content = format_comment(content)
    if len(content) == 0:
        return error.request.ParamCustomized.dump(
            reason=u'评论内容不能为空')
    if char_count_ty(content) > 500:
        return error.request.ParamCustomized.dump(
            reason=u'评论内容不能超过500个汉字')

    #
    book = Book.get(book_id)
    if book is None:
        return error.data.BookNotFound.dump()

    #
    chapter = None
    if chapter_id != 0:
        chapter = Chapter.get(chapter_id)
        if chapter is None:
            return error.data.ChapterNotFound.dump()
        if chapter.book_id != book.id:
            return error.request.Params(u'章节信息不正确').dump()

    #
    user = User.get(user_id)
    if user is None:
        return error.data.UserNotFound.dump()
    if user.check_disable_speak():
        return error.data.DisableSpeak.dump()

    # 检查马甲是否属于当前管理员
    manager_id = request.uid
    puppets = ManagerPuppets.get(manager_id)
    user_ids = puppets[:]
    if user_id not in user_ids:
        return error.request.Params(u'无权限使用该账号发评论').dump()

    # 发表评论
    comment = comment_logic.release_comment(user, book, chapter, content)

    # 记录最后一次使用的马甲
    last_used_puppet = LastUsedPuppet.get(manager_id)
    last_used_puppet.user_id = user_id
    last_used_puppet.put()

    # 记录代发评论的事件
    ManageOperationLog.log(ManageOperationLog.OPERATION_PUPPET_COMMENTING,
                           user_id, Comment.__name__, comment.id,
                           comment.dump_detail())

    return dict_result(comment.dump_detail())


# ====================后台章节预览结束====================


# ====================后台作品搜索开始====================

def get_valid_datetime_str(param_name, default_datetime_value=None):
    fmt = '%Y-%m-%d %H:%M:%S'
    datetime_str = param(param_name, None, tounicode)
    try:
        # 测试传入的日期时间字符串是否正确，否则返回默认值
        datetime.datetime.strptime(datetime_str, fmt)
        return datetime_str
    except:
        if default_datetime_value is not None:
            return default_datetime_value.strftime(fmt)
        else:
            return ''


def get_book_search_params(set_default_release_time_range=True):
    offset, count, _, _ = pagelet()
    release_time_start, release_time_end = None, None
    if set_default_release_time_range:
        release_time_end = datetime.datetime.now()
        release_time_start = release_time_end - datetime.timedelta(days=1)

    params = {
        'book_id': param('book_id', None, fx.p(toint, default=None)),
        'keyword': param('keyword', None, tounicode),
        'create_time_start': get_valid_datetime_str('create_time_start'),
        'create_time_end': get_valid_datetime_str('create_time_end'),
        'release_time_start': get_valid_datetime_str('release_time_start',
                                                     release_time_start),
        'release_time_end': get_valid_datetime_str('release_time_end',
                                                   release_time_end),
        'word_count_max': param('word_count_max', None,
                                fx.p(toint, default=None)),
        'word_count_min': param('word_count_min', None,
                                fx.p(toint, default=None)),
        'offset': offset,
        'count': count,
        'order_field': param('order_field', 'release_time_value', tounicode),
        'order_type': param('order_type', 0, toint),
        'signed': param('signed', None, fx.p(toint, default=None))
    }

    return params


# --------------------------- serial ---------------------------

def get_serial_params(set_default_release_time_range=True):
    offset, count, _, _ = pagelet()
    release_time_start, release_time_end = None, None
    if set_default_release_time_range:
        release_time_end = datetime.datetime.now()
        release_time_start = release_time_end - datetime.timedelta(days=1)

    params = {
        'book_id': param('book_id', None, fx.p(toint, default=None)),
        'keyword': param('keyword', None, tounicode),
        'create_time_start': get_valid_datetime_str('create_time_start'),
        'create_time_end': get_valid_datetime_str('create_time_end'),
        'release_time_start': get_valid_datetime_str('release_time_start',
                                                     release_time_start),
        'release_time_end': get_valid_datetime_str('release_time_end',
                                                   release_time_end),
        'word_count_max': param('word_count_max', None,
                                fx.p(toint, default=None)),
        'word_count_min': param('word_count_min', None,
                                fx.p(toint, default=None)),
        'offset': offset,
        'count': count,
        'order_field': param('order_field', 'release_time_value', tounicode),
        'order_type': param('order_type', 0, toint),
        'signed': param('signed', None, fx.p(toint, default=None)),
        'serial_update': 0
    }

    return params


@get(request_path('/serial.html'))
@set_response(tpl_path('/serial'))
def book_serial_html():
    params = get_serial_params()
    manager_id = getattr(request, 'uid', 0)
    manager = ManageUser.get(manager_id or 0)
    is_root = 0
    if manager and (manager.role == ManageUser.ROLE_ROOT or "force_delete_book" in manager.permission_ids
                    or "force_rename_book" in manager.permission_ids):
        is_root = 1
    params['order_field_list'] = ManageBook.get_search_order_field_list()
    params['is_root'] = is_root
    # print '--'*20, params
    return {'json_params': json.dumps(params)}


@get(request_path('/serial.json'))
@set_response()
def book_serial_json():
    print '='*50, 1
    fmt = '%Y-%m-%d %H:%M:%S'
    # params = get_book_search_params(False)
    params = get_serial_params(False)
    print '=' * 50, params

    def change_param_to_datetime(param_name):
        p = params[param_name]
        params[param_name] = datetime.datetime.strptime(p, fmt) if p else None

    # 转换查询参数
    change_param_to_datetime('create_time_start')
    change_param_to_datetime('create_time_end')
    change_param_to_datetime('release_time_start')
    change_param_to_datetime('release_time_end')
    order_field_str = params['order_field']
    order_type_str = ['DESC', 'ASC'][params['order_type']]

    # 查询符合条件的数据

    print '=' * 50, 2
    book_ids, total, offset = Charts.book_ids_list(), 0, 1
    #ManageBook.query_books(params, order_field_str,order_type_str)
    print '=' * 50, 3
    book_dict = Book.gets(*book_ids)
    # print 'book'*10, book_dict
    """ :type: dict[int, Book] """
    dump_attrs = [
        'author_tag', 'word_count', 'image_count', 'tag_words',
        'create_time_value', 'comment_count', 'published_chapter_count',
        'read_count', 'pumpkin_info', 'favorer_count', 'share_count',
        'rewarded_coins', 'finished', 'starred', 'signed', 'top_level_info', 'channels']
    books = (book_dict[fi_id] for fi_id in book_ids if book_dict.get(fi_id))
    print '=' * 50, 4

    print '=' * 50, 5
    # books_dump = [fi_book.dump_tag(*dump_attrs) for fi_book in books]

    books_dump = []
    for fi_book in books:
        temp = fi_book.dump_tag(*dump_attrs)
        temp['serial_update'] = Charts.fetch(fi_book.id).serialUpdate
        print '-'*30, temp
        books_dump.append(temp)
    print '-' * 30, 'temp_books_dump', books_dump[0]

    print '=' * 50, 6, '!!!!!!!!!!!!!!!!!!books_dump-type ', type(books_dump), '------------ books_dump - date ', books_dump[0]
    params['books'] = books_dump
    params['total'] = total
    params['offset'] = offset

    # print params

    # 将日期时间转换回字符串
    def format_time_to_params(param_name):
        t = params[param_name]
        params[param_name] = t.strftime(fmt) if t else ''

    format_time_to_params('create_time_start')
    format_time_to_params('create_time_end')
    format_time_to_params('release_time_start')
    format_time_to_params('release_time_end')
    print '=' * 50, 7
    print 'params ', params
    result = dict_result(params)
    # print '=' * 50, result
    return result


# --------------------------- serial ---------------------------


@get(request_path('/search.html'))
@set_response(tpl_path('/search'))
def book_search_html():
    params = get_book_search_params()
    manager_id = getattr(request, 'uid', 0)
    manager = ManageUser.get(manager_id or 0)
    is_root = 0
    if manager and (manager.role == ManageUser.ROLE_ROOT or "force_delete_book" in manager.permission_ids
                    or "force_rename_book" in manager.permission_ids):
        is_root = 1
    params['order_field_list'] = ManageBook.get_search_order_field_list()
    params['is_root'] = is_root
    return {'json_params': json.dumps(params)}


@get(request_path('/search.json'))
@set_response()
def book_search_json():
    fmt = '%Y-%m-%d %H:%M:%S'
    params = get_book_search_params(False)

    def change_param_to_datetime(param_name):
        p = params[param_name]
        params[param_name] = datetime.datetime.strptime(p, fmt) if p else None

    # 转换查询参数
    change_param_to_datetime('create_time_start')
    change_param_to_datetime('create_time_end')
    change_param_to_datetime('release_time_start')
    change_param_to_datetime('release_time_end')
    order_field_str = params['order_field']
    order_type_str = ['DESC', 'ASC'][params['order_type']]

    # 查询符合条件的数据
    book_ids, total, offset = ManageBook.query_books(params, order_field_str,
                                                     order_type_str)
    book_dict = Book.gets(*book_ids)
    """ :type: dict[int, Book] """
    dump_attrs = [
        'author_tag', 'word_count', 'image_count', 'tag_words',
        'create_time_value', 'comment_count', 'published_chapter_count',
        'read_count', 'pumpkin_info', 'favorer_count', 'share_count',
        'rewarded_coins', 'finished', 'starred', 'signed', 'top_level_info', 'channels']
    books = (book_dict[fi_id] for fi_id in book_ids if book_dict.get(fi_id))
    books_dump = [fi_book.dump_tag(*dump_attrs) for fi_book in books]

    params['books'] = books_dump
    params['total'] = total
    params['offset'] = offset

    # 将日期时间转换回字符串
    def format_time_to_params(param_name):
        t = params[param_name]
        params[param_name] = t.strftime(fmt) if t else ''

    format_time_to_params('create_time_start')
    format_time_to_params('create_time_end')
    format_time_to_params('release_time_start')
    format_time_to_params('release_time_end')

    result = dict_result(params)
    return result


@post(request_path('/force_delete.json'))
@set_response()
def book_force_delete_json():
    manager_id = getattr(request, 'uid', 0)
    manager = ManageUser.get(manager_id or 0)
    is_root = 0
    if manager and (manager.role == ManageUser.ROLE_ROOT or "force_delete_book" in manager.permission_ids):
        is_root = 1
    if not is_root:
        return Error(1, u'没有权限').dump()
    book_id = param('book_id', 0, lambda x: x and int(x))
    book = Book.get(book_id or 0)
    if not book:
        return Error(1, u'没有权限').dump()

    book.delete()
    change_attrs = ['book_id:%s' % book_id]
    manage_operation_log(*change_attrs)
    return dict_result(None)


@get(request_path('/rename.html'))
@set_response(tpl_path('/rename'),
              layout_processor=widget_dialog_layout_processor)
def book_force_rename_html():
    book_id = param('book_id', 0, toint)
    book = Book.get(book_id)
    ret = {
        'author_name': book.author.nickname,
        'book_id': book_id,
        'book_name': book.name,
        'book_summary': book.summary,
    }
    return widget_result('book_rename',
                         u'强制修改书籍名称',
                         ret).dump()


@post(request_path('/force_rename.json'))
@set_response()
def book_force_rename_json():
    manager_id = getattr(request, 'uid', 0)
    manager = ManageUser.get(manager_id or 0)
    is_root = 0
    if manager and (manager.role == ManageUser.ROLE_ROOT or "force_rename_book" in manager.permission_ids):
        is_root = 1
    if not is_root:
        return Error(1, u'没有权限').dump()
    book_id = param('book_id', 0, lambda x: x and int(x))
    book_name = param('book_name', '')
    book_name = tounicode(book_name) if book_name else book_name
    if not book_name:
        return Error(1, u'请输入书籍名称').dump()
    if display_length(book_name) > 24:
        return Error(1, u'书籍名称应小于12字符').dump()
    book = Book.get(book_id or 0)
    if not book:
        return Error(1, u'不存在该书籍').dump()

    book.name = book_name
    book.put()

    ManageOperationLog.log(ManageOperationLog.OPERATION_BOOK_RENAME,
                           book.author_id, Book.__name__, book.id,
                           book.dump_detail())
    # 通知索引更新
    SearchUpdateNotification.send(SearchUpdateNotification.MODEL_NAME_BOOK, book.id,
                                  SearchUpdateNotification.ACTION_UPDATE)
    return dict_result({"book_name": book.name})


@post(request_path('/tag/change/<book_id:int>.json'))
@set_response()
def change_book_tags(book_id):
    book = Book.get(book_id)
    if not book:
        return Error(1, u'该书不存在').dump()

    tags = param('tags', [], lambda x: [fi_i.strip() for fi_i in re.split(u' |\r|\n|\t', tounicode(x))])
    if tags:
        tag_list = [fi_tag for fi_tag in tags if fi_tag]
        if len(tag_list) > 10:
            return Error(2, u'不能超过10个标签。').dump()
        for fi_tag in tag_list:
            if len(fi_tag) > 6:
                return Error(3, u'每个标签不能超过6个汉字。').dump()

        book.update_tags(*tag_list)
        return dict_result(u'  '.join([fi_t.tag for fi_t in book.tags]))
    else:
        return Error(4, u'参数错误。').dump()


@get(request_path('/change/star/<book_id:int>.json'))
@set_response()
def change_book_star(book_id):
    book = Book.get(book_id)
    if not book:
        return Error(1, u'该书不存在').dump()

    book.starred = False if book.starred else True
    book.put()

    if book.starred:
        Notice.put_book_starred(book.author_id, book.id)

        alert = u'你好，你的作品《%s》已升级为星级作品！' % book.name
        Push.push_msg(book.author, alert=alert,
                      action=typ['notice_official'].render())

    return dict_result(book.dump_tag('starred'))


@post(request_path('/change/sign/<book_id:int>.json'))
@set_response()
def change_book_sign(book_id):
    manager_id = getattr(request, 'uid', 0)
    manager = ManageUser.get(manager_id or 0)
    if not (manager and (manager.role == ManageUser.ROLE_ROOT or "core_book_sign" in manager.permission_ids)):
        return Error(1, u'没有权限').dump()

    book = Book.get(book_id)
    if not book:
        return Error(1, u'该书不存在').dump()

    sign = 0 if book.sign_status > 0 else 1

    book.sign_info.status = 4 if sign else 3
    book.sign_info.handle_time = datetime.datetime.now()
    book.sign_info.put()

    book.sign_status = 1 if sign else 0
    book.put()
    # 将签约作品和解除签约的作品同步到ES中
    if sign:
        Notice.put_book_signed(book.author_id, book.id)

        alert = u'你好，你的作品《%s》已升级为签约作品！' % book.name
        Push.push_msg(book.author, alert=alert,
                      action=typ['notice_official'].render())
        DistributionChannelSearcher.add_to_index(book)
    else:
        # 如果书籍存在分销渠道， 则现将分销渠道删除， 并移除分销索引
        if book.channels:
            from ricebag.logic.distributionchannel.distributionchannel import distribution_channel_book_delete
            distribution_channel_book_delete((book_id,))
        # 同时删除书的分销渠道的基本信息
        from ricebag.model.distributionchannel import DistributionChannelCommonBook
        dccb = DistributionChannelCommonBook.fetch(book_id)
        if dccb:
            dccb.delete()
        DistributionChannelSearcher.delete_from_index(book_id)

    BookSearcher.add_to_index(book)
    return dict_result(book.dump_tag('signed'))


@get(request_path('/topbook/set/<book_id:int>.json'))
@set_response()
def set_top_book_json(book_id):
    book = Book.get(book_id)
    if not book:
        return Error(1, u'该作品不存在').dump()

    tag = Tag.get(param('tag_id', 0, toint))
    if not tag:
        return Error(1, u'标签不存在')
    if not tag.official:
        return Error(1, u'标签不是官方标签')

    level = param('level', 0, toint)
    if level not in TopBook.LEVELS:
        return Error(1, u'错误的等级')

    TopBook.set_top(book.id, tag.id, level)
    return dict_result(book.dumps('top_level_info'))


@get(request_path('/topbook/remove/<book_id:int>.json'))
@set_response()
def remove_top_book_json(book_id):
    book = Book.get(book_id)
    if not book:
        return Error(1, u'作品不存在').dump()

    TopBook.remove_top(book.id)
    return dict_result(None)


@get(request_path('/widget_share_stats.html'))
@set_response(tpl_path('/widget_share_stats'),
              layout_processor=widget_dialog_layout_processor)
def widget_share_stats_html():
    result = widget_result('widget_share_stats', title=u'作品分享统计')

    book_id = param('book_id', None, toint)
    book = Book.get(book_id) if book_id else None
    if not book:
        return result.set_param({'error': u'作品不存在'}).dump()

    share_record_stats = BookShareRecord.stats_by_book(book_id)

    stats = []
    for destination, count in share_record_stats:
        destination_name = BookShareRecord.DESTINATIONS_NAME[destination]
        stats.append({'destination': destination_name, 'count': count})

    book_dump = book.dump_tag('author_tag')

    return result.set_param({'book': book_dump,
                             'stats': stats}).dump()


@get(request_path('/widget_reward.html'))
@set_response(tpl_path('/widget_reward'),
              layout_processor=widget_dialog_layout_processor)
def widget_reward_html():
    offset, count = 0, 6
    result = widget_result('widget_see_book_reward', title=u'作品打赏信息')
    book_id = param('book_id', None, toint)
    select_type = param('select_type', 'gift', unicode)
    book = Book.get(book_id) if book_id else None
    if not book:
        return result.set_param({'error': u'作品不存在'}).dump()

    book_dump = book.dump_tag('author_tag')
    return result.set_param({'book': book_dump,
                             'offset': offset,
                             'count': count,
                             'select_type': select_type,
                             }).dump()


@get(request_path('/reward.json'))
@set_response()
def widget_reward_json():
    offset, count, _, _ = pagelet()
    book_id = param('book_id', None, toint)
    book = Book.get(book_id) if book_id else None
    if not book:
        return Error(1, u'作品不存在')
    select_type = param('select_type', None, unicode)
    if select_type not in ('gift', 'contributor', 'reward'):
        select_type = 'gift'

    total = 0
    gifts = {
        'gift_num': 0,
        'coins': 0,
        'gifts': [],
    }
    contributors = []
    if select_type == 'gift':
        tmp_count = BookRewardCount.fetch(book.id)
        if tmp_count:
            gifts['gift_num'] = tmp_count.gifts
            gifts['coins'] = tmp_count.coins
            search_parms = {
                'book_id': book_id,
                'offset': offset,
                'count': count
            }
            tmp_gifts, total = ManageBookGiftCount.get_list(search_parms)
            gifts['gifts'] = tmp_gifts
    elif select_type == 'contributor':
        contributor_zset = BookContributorsZSet.get(book_id)
        total = contributor_zset.size()
        index_id = offset
        for fi_item in contributor_zset.range_with_score(offset, count):
            index_id += 1
            contributor_id, coins = fi_item
            contributor = User.get(contributor_id)
            if not contributor:
                continue
            contributor_info = contributor.dump_tag()
            gift_items = ManageBookContributorGiftCount.get_gift_count_info(
                book_id=book_id, contributor_id=contributor_id)
            contributors.append({
                'index_id': index_id,
                'contributor_info': contributor_info,
                'gift_items': gift_items,
                'coins': coins,
            })

    return dict_result({
        'offset': offset,
        'count': count,
        'total': total,
        'gifts': gifts,
        'contributors': contributors,
    })


# ====================后台作品搜索结束====================


# ====================后台作品编辑开始===========================

@get(request_path('/write/index.html'))
@set_response(tpl_path('/write/index'))
def write_index_html():
    me = request.manager
    is_admin = me.role == ManageUser.ROLE_ROOT
    return {'json_params': json.dumps({'is_admin': is_admin})}


@get(request_path('/write/author/list.json'))
@set_response()
def write_author_list():
    mu = request.manager
    author_ids = mu.author_ids[:]
    author_dict = User.gets(*author_ids)
    authors = [author_dict.get(fi_author_id) for fi_author_id in author_ids
               if author_dict.get(fi_author_id)]
    return dict_result(
        {
            'authors': [fi_author.dump_tag() for fi_author in authors]
        }
    )


@get(request_path('/write/books/<user_id:int>.json'))
@set_response()
def write_books(user_id):
    user = User.get(user_id)
    if user is None:
        return Error(10201, u'您要添加的用户不存在。').dump()
    return dict_result({'books': [fi_book.dump_tag('author_id')
                                  for fi_book in user.books]})


@post(request_path('/write/author/add/<user_id:int>.json'))
@set_response()
def write_author_add(user_id):
    user = User.get(user_id)
    if user is None:
        return Error(10201, u'您要添加的用户不存在。').dump()

    mu = request.manager
    if user.id not in mu.author_ids:
        mu.author_ids.append(user.id)
        # 每个管理员只允许同时操作10个作者的作品
        while len(mu.author_ids) > 10:
            del mu.author_ids[0]
        mu.author_ids.put()
    return dict_result(None)


@post(request_path('/write/author/remove/<user_id:int>.json'))
@set_response()
def write_author_remove(user_id):
    user = User.get(user_id)
    if user is None:
        return Error(10201, u'您要删除的用户不存在。').dump()
    mu = request.manager
    if user.id in mu.author_ids:
        mu.author_ids.remove(user.id)
        mu.author_ids.put()
    return dict_result(None)


@get(request_path('/write/book/create/<user_id:int>.html'))
@set_response(tpl_path('/write/create'),
              layout_processor=widget_dialog_layout_processor)
def book_create_html(user_id):
    return widget_result('widget_create_book', u'添加作品',
                         {'user_id': user_id}).dump()


@post(request_path('/write/book/create/<user_id:int>.json'))
@set_response()
def book_create_json(user_id):
    if user_id not in request.manager.author_ids:
        return Error(2, u'权限不足').dump()

    user = User.get(user_id)
    name = param('name', None, tounicode)
    summary = param('summary', '', tounicode)
    create_timestamp = None  # 不需要防重复创建
    public = True

    tag_list = param('tags', [], lambda x: [fi_i.strip() for fi_i in tounicode(x).split(',') if fi_i and fi_i.strip()])

    # 上传图片
    cover_data = None
    temp_file_object_id = param('temp_file_id', 0, int)
    manage_temp_file = ManageTempFile.get(temp_file_object_id)
    if manage_temp_file and manage_temp_file.file_id:
        cover_data = manage_temp_file.file_data

    book, error_json = booklogic.create_book(user=user, name=name, summary=summary, cover_data=cover_data,
                                             create_timestamp=create_timestamp, tag_list=tag_list,
                                             public=public, from_admin=True)

    if error_json:
        return error_json
    else:
        return dict_result({
            'book': book.dump_tag('author_id')
        })


@post(request_path('/write/book/delete/<book_id:int>.json'))
@set_response()
def book_delete_json(book_id):
    book = Book.get(book_id)
    """ :type: Book """
    if book is None:
        return dict_result(None)

    if not book.can_delete:
        return Error(2, book.ext.delete_limit_msgs[0]).dump()

    if book.author_id not in request.manager.author_ids:
        return Error(2, u'权限不足').dump()

    send_sensitive_mail(request.uid, u'删除作品《%s》(%s)' % (book.name, book.id))

    ManageOperationLog.log(ManageOperationLog.OPERATION_BOOK_DELETING,
                           book.author_id, Book.__name__, book.id,
                           book.dump_detail())

    success, error_json = booklogic.delete_book(book_id, book.author_id, True)
    if error_json:
        return error_json
    else:
        return dict_result(None)


@get(request_path('/write/book/update/<book_id:int>.html'))
@set_response(tpl_path('/write/update'),
              layout_processor=widget_dialog_layout_processor)
def book_create_html(book_id):
    book = Book.get(book_id)
    json_params = {
        'book_id': book_id,
        'name': book.name,
        'summary': book.summary,
        'tags': book.tags_text,
        'cover_url': book.cover_url
    }
    return widget_result('widget_update_book',
                         u'修改作品《%s》' % book.name,
                         json_params).dump()


@post(request_path('/write/book/update/<book_id:int>.json'))
@set_response()
def update_book_info(book_id):
    book = Book.get(book_id)
    user = book.author
    if book is None or user is None:
        return Error(1, u'参数错误').dump()
    if user.id not in request.manager.author_ids:
        return Error(2, u'权限不足').dump()

    name = param('name', None, tounicode)
    summary = param('summary', '', tounicode)

    cover_data = None
    # 上传图片
    temp_file_object_id = param('temp_file_id', 0, int)
    manage_temp_file = ManageTempFile.get(temp_file_object_id)
    if manage_temp_file and manage_temp_file.file_id:
        cover_data = manage_temp_file.file_data

    tag_list = param('tags', None,
                     lambda x: [fi_i.strip() for fi_i in tounicode(x).split(',') if fi_i and fi_i.strip()])

    send_sensitive_mail(request.uid, u'更新作品信息《%s》(%s)' % (book.name, book.id))

    book, error_json = booklogic.update_book(book_id, user.id, name, summary, cover_data=cover_data, tag_list=tag_list,
                                             public=None, finished=None, order_type=None, view_type=None,
                                             from_admin=True)

    if error_json:
        return error_json
    else:
        return dict_result({'book': book.dump_tag('author_id')})


@get(request_path('/write/chapter/list/<book_id:int>.json'))
@set_response()
def book_chapters_json(book_id):
    book = Book.get(book_id)
    if not book:
        return Error(1, u'该作品不存在').dump()

    if book.author_id not in request.manager.author_ids:
        return Error(2, u'权限不足').dump()

    chapter_ids = book.chapter_ids[:]
    chapter_dict = Chapter.gets(*chapter_ids)

    chapters = [chapter_dict[fi_cid].dump_tag('author_tag', 'order_value')
                for fi_cid in chapter_ids if chapter_dict.get(fi_cid)]

    sort_chapters = sorted(chapters, key=lambda chapter: chapter['order_value'], reverse=True)

    return dict_result({
        'chapters': sort_chapters
    })


@get(request_path('/write/chapter/content/<chapter_id:int>.json'))
@set_response()
def book_get_chapter(chapter_id):
    chapter = Chapter.get(chapter_id)
    content_text = ChapterContentUtil.gen_editable_body_inner_content(chapter.content)
    return dict_result({
        'title': chapter.title,
        'content': content_text,
        'author_tag': chapter.author_tag
    })


@post(request_path('/write/chapter/create/<book_id:int>.json'))
@set_response()
def book_chapter_create(book_id):
    book = Book.get(book_id)
    if book is None or book.author is None:
        return Error(1, u'参数错误').dump()
    if book.author_id not in request.manager.author_ids:
        return Error(2, u'权限不足').dump()

    title = param('title', None, tounicode)
    content = param('content', None, tounicode)
    image_manage_file_id = param('image_manage_file_id', 0, lambda x: int(x) if x else 0)
    publish = param('publish', 0, int) != 0

    # 如果发的是图片章节，直接把图片地址作为content
    image_content = None
    if image_manage_file_id:
        image_manage_file = ManageTempFile.get(image_manage_file_id)
        image_content = image_manage_file.file_data
        if not ImageUtil.is_image(image_content):
            return Error(1, u'上传的文件不是图片').dump()
        width, height = ImageUtil.size(image_content)
        content = u'<img src="a1.jpg" width="%s" height="%s"/>' % (width, height)

    if content is None or len(content) <= 0:
        return Error(10512, u'章节内容不能为空').dump()

    # 为了保持跟客户端发布章节流程一致，这里也是按照“创建章节-上传内容-上传附件（可选）-发布章节”这样的顺序进行操作

    now = datetime.datetime.now()
    # 创建章节
    chapter, error_json = booklogic.create_chapter(book_id, book.author_id, create_timestamp=None, title=title,
                                                   timestamp=now, order_value=None, from_admin=True)
    if error_json:
        return error_json

    # 成功创建章节后上传内容
    # 生成一份完整的content html文件内容
    chapter_content, plain_content = ChapterContentUtil. \
        gen_formatted_chapter_content_from_pure_content(chapter.title, content, timestamp=now, from_manage=True)
    file_data = tobytes(chapter_content)
    # 如果是图片章节，需要上传附件
    if image_manage_file_id and image_content:
        chapter, result_attachments, error_json = booklogic.upload_chapter_content(book_id, chapter.id, book.author_id,
                                                                                   file_data=file_data,
                                                                                   attachments=['a1.jpg'],
                                                                                   from_admin=True)
        chapter.upload_attachment('a1.jpg', image_content, 'jpg')
        chapter.put()

    else:
        chapter, result_attachments, error_json = booklogic.upload_chapter_content(book_id, chapter.id, book.author_id,
                                                                                   file_data=file_data,
                                                                                   attachments=None,
                                                                                   from_admin=True)
    if error_json:
        return error_json

    # 如果选择发布，搞定内容之后就直接发布章节
    if publish:
        chapter, error_json = booklogic.publish_chapter(book_id, chapter.id, book.author_id)

    if error_json:
        return error_json

    return dict_result({
        'chapter': {
            'id': chapter.id,
            'title': chapter.title,
            'content': plain_content,
            'author_tag': chapter.author_tag
        }
    })


@post(request_path('/write/chapter/delete/<book_id:int>/<chapter_id:int>.json'))
@set_response()
def book_chapter_delete(book_id, chapter_id):
    chapter = Chapter.get(chapter_id)
    if not chapter:
        return dict_result(None)
    if chapter.book is None or chapter.book.id != book_id:
        return error.request.Params.dump(reason=u'章节ID与书ID不匹配')
    if chapter.book.author_id not in request.manager.author_ids:
        return Error(2, u'权限不足').dump()

    send_sensitive_mail(request.uid, u'删除章节《%s》(%s)' % (chapter.title, chapter.id))

    success, error_json = booklogic.delete_chapter(chapter_id=chapter_id, book_id=book_id,
                                                   user_id=chapter.book.author_id,
                                                   from_admin=False)
    if error_json:
        return error_json
    else:
        return dict_result(Book.get(book_id).dump_detail())


@post(request_path('/write/chapter/save/<book_id:int>/<chapter_id:int>.json'))
@set_response()
def book_save_chapter(book_id, chapter_id):
    title = param('title', None, tounicode)
    content = param('content', None, tounicode)
    publish = param('publish', 0, int) != 0
    if content is None or len(content) <= 0:
        return Error(10512, u'章节内容不能为空').dump()
    chapter = Chapter.get(chapter_id)
    if chapter is None or chapter.book is None or chapter.book.id != book_id:
        return Error(1, u'参数错误').dump()

    if chapter.book.author_id not in request.manager.author_ids:
        return Error(2, u'权限不足').dump()

    send_sensitive_mail(request.uid, u'更改章节内容《%s》(%s)' % (chapter.title, chapter.id))

    # 更新章节标题
    chapter, error_json = booklogic.update_chapter(book_id=book_id, chapter_id=chapter_id,
                                                   user_id=chapter.book.author_id, title=title)
    if error_json:
        return error_json

    # 上传章节内容
    publish = True
    authorspeak = chapter.authorspeak_content
    chapter_content, plain_content = ChapterContentUtil. \
        gen_formatted_chapter_content_from_pure_content(chapter.title, content, timestamp=chapter.timestamp,
                                                        from_manage=True, authorspeak=authorspeak)
    file_data = tobytes(chapter_content)
    chapter, result_attachments, error_json = booklogic.upload_chapter_content(book_id, chapter.id,
                                                                               chapter.book.author_id,
                                                                               file_data=file_data,
                                                                               attachments=None,
                                                                               from_admin=True)
    if error_json:
        return error_json

    # 发布章节
    if chapter and publish:
        chapter, error_json = booklogic.publish_chapter(book_id, chapter.id, chapter.book.author_id)
    if error_json:
        return error_json

    return dict_result({
        'chapter': {
            'id': chapter.id,
            'title': chapter.title,
            'content': plain_content,
            'author_tag': chapter.author_tag
        }
    })

# ====================后台作品编辑结束===========================
