/**
 * Created by eisen on 14-9-1.
 */
require(['jquery', 'avalon', 'tym'], function($, avalon, TYM) {
    var vModelId = 'core_book_search';
    var searchModel = null;

    // 每次查询时需要提交的参数名称
    var basePostParamNames = [
        'book_id',
        'keyword',
        'signed',
        'create_time_start', 'create_time_end',
        'release_time_start', 'release_time_end',
        'word_count_max', 'word_count_min',
        'order_field', 'order_type',
        'offset', 'count'
    ];

    // 将src里面的参数填充到dest，仅限postParamNames里有的属性
    function fill_params(src, dest, copyToHistory, extParams) {
        var paramNames = basePostParamNames;
        if (extParams) {
            paramNames = paramNames.concat(extParams);
        }

        paramNames.forEach(function(paramName) {
            var value = src[paramName];
            if (value == null || typeof(value) == 'undefined') {
                dest[paramName] = '';
            } else {
                dest[paramName] = value;
            }

            if (copyToHistory) {
                dest['history_' + paramName] = value;
            }
        });
        return dest;
    }

    // 将历史数据提取出来做为提交的参数
    function load_history_params() {
        var result = {};
        basePostParamNames.forEach(function(paramName) {
            result[paramName] = searchModel['history_' + paramName];
        });
        return result;
    }

    // 定义加载数据的方法
    function loadData(params, offset, replaceUrl) {
        var postParams = fill_params(params, {});

        postParams.offset = offset;
        postParams.count = searchModel.pager.count;
        postParams.signed=postParams.signed == -1? null : postParams.signed

        var apiUrl = '/manage/core/book/search.json';
        var directRequestUrl = '/manage/core/book/search.html';

        $.get(apiUrl, postParams, TYM.genSuccCb(function(result) {
            var resultData = result.data;
            fill_params(resultData, searchModel, true);
            resultData.books.forEach(function(book) {
                book.tags_str = book.tag_words.join(' ');
            });
            searchModel.books = resultData.books;
            TYM.components.pager.update(vModelId, resultData.total,
                resultData.offset, resultData.count);

            // 改变浏览器地址栏的URL，模拟直接请求，只有get请求才能这样玩
            TYM.addUrlToHistory(directRequestUrl, postParams, replaceUrl);
        }), 'json');
    }

    // 新的搜索
    function clickSearch() {
        loadData(fill_params(searchModel, {}), 0);
    }

    // 修改标签
    function clickSaveTags(book) {
        var url = TYM.fillTemplate(
            '/manage/core/book/tag/change/${book_id}.json',
             {book_id: book.id});
        $.post(url, {tags: book.tags_str}, TYM.genSuccCb(function(result) {
            book.tags_str = result.data;
            alert('修改成功');
        }), 'json');
    }

    // 更改星级作品
    function changeStar(book) {
        var confirmMsg = TYM.fillTemplate(
            '确认更改《${book_name}》的星级作品设置？', {book_name: book.name});
        if (!confirm(confirmMsg)) {
            return;
        }
        var url = TYM.fillTemplate(
            '/manage/core/book/change/star/${book_id}.json',
            {book_id: book.id});
        $.get(url, TYM.genSuccCb(function(result) {
            book.starred = result.data.starred;
        }), 'json');
    }

    function changeSign(book){
        if (!book.signed){
            var confirmMsg = TYM.fillTemplate(
                '确认更改《${book_name}》为签约作品么？', {book_name: book.name});
        }
        else {
            console.log(book.channels, typeof book.channels);
            if (book.channels.length > 0) {
                var confirmMsg = TYM.fillTemplate(
                    '确认解约《${book_name}》签约作品, 并同时将分销渠道的该书籍下架么？', {book_name: book.name});
            }
            else {
                var confirmMsg = TYM.fillTemplate(
                    '确认更改《${book_name}》解除签约作品么？', {book_name: book.name});
            }
        }

        if (!confirm(confirmMsg)) {
            return;
        }
        var url = TYM.fillTemplate(
            '/manage/core/book/change/sign/${book_id}.json',
            {book_id: book.id});
        $.post(url, TYM.genSuccCb(function(result) {
            book.signed = result.data.signed;
        }), 'json');
    }

    function showBookShareRecord(book) {
        var widgetUrl = '/manage/core/book/widget_share_stats.html';
        TYM.loadWidget('get', widgetUrl, {book_id: book.id});
    }

    function showBookRewardedRecord(book) {
        var widgetUrl = '/manage/core/book/widget_reward.html';
        TYM.loadWidget('get', widgetUrl, {book_id: book.id, select_type: 'gift'});
    }

    // 定义model，在avalon.define方法里面，不要执行任何方法，只能做属性和方法的定义，
    // 最后一定要返回所有定义的avalon vmodel列表
    TYM.initPage(true, function(pageParams) {
        searchModel = avalon.define(vModelId, function(vm) {
            TYM.components.pager.init(
                vModelId, vm, pageParams.offset, pageParams.count,
                function (newOffset) {
                    // 翻页逻辑
                    // 从history取数据
                    loadData(load_history_params(), newOffset);
                }
            );

            vm.order_field_list = pageParams.order_field_list;
            vm.is_root = pageParams.is_root;
            fill_params(pageParams, vm, true);
            vm.books = [];
            vm.clickSearch = clickSearch;
            vm.clickSaveTags = clickSaveTags;
            vm.changeStar = changeStar;
            vm.changeSign = changeSign;
            vm.showBookShareRecord = showBookShareRecord;
            vm.showBookRewardedRecord = showBookRewardedRecord;
            vm.deleteBook = function (book) {
                var msg = '确定删除 ' + book.name;
                if (confirm(msg)) {
                    var tmp_parms = {book_id: book.id};
                    var postUrl = '/manage/core/book/force_delete.json';
                    $.post(postUrl, tmp_parms,
                        TYM.genSuccCb(function (result) {
                            alert('操作成功');
                            loadData(fill_params(searchModel, {}), searchModel.pager.offset, true);
                        }), 'json');
                }
            };
        });
        return [searchModel];
    }, function() {
        // avalon扫描后首次加载数据
        loadData(fill_params(searchModel, {}), searchModel.pager.offset, true);
        // 初始化日期控件
        TYM.components.datetimepicker.init('.form-date', TYM.getContentPanel());
    }, function() {
        // 离开页面前执行的清理工作
        TYM.components.datetimepicker.remove('.form-date', TYM.getContentPanel());
    });
});
