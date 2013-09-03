$(function() {
    /**
     * Any links found in the accordion header (package subscription list)
     * should work as links, not as a details toggle.
     */
     $('.accordion-toggle a').click(function(evt) {
        evt.stopPropagation();
     });

     var unsubscribe_url = $('#unsubscribe-url').html();
     var unsubscribe_all_url = $('#unsubscribe-all-url').html();

     $('.unsubscribe-package').click(function(evt) {
        var $this = $(this);
        $.post(unsubscribe_url, {
            'package': $this.data('package'),
            'email': $this.data('email')
        }).done(function(data) {
            var $group = $this.closest('.accordion-group')
            $group.fadeOut(500, function() {
                if ($group.siblings('.accordion-group').length === 0) {
                    $group.parent().before('<em>No subscriptions!</em>');
                    // Apart from the updated text, the remove all unsubscribe-all
                    // button is no longer necessary.
                    $group.parent().closest('.accordion-group').find('.unsubscribe-all').fadeOut();
                    $group.parent().remove();
                } else {
                    $group.remove();
                }
            });
        });
        return false;
     });

     $('.unsubscribe-all').click(function(evt) {
        var $this = $(this);
        $.post(unsubscribe_all_url, {
            'email': $this.data('email')
        }).done(function(data) {
            // Remove all previously existing subscriptions from the page.
            var $group = $this.closest('.accordion-group');
            var to_remove = $group.find('.accordion-group');
            $this.fadeOut();
            to_remove.fadeOut(500, function() {
                to_remove.parent().before('<em>No subscriptions!</em>');
                to_remove.parent().remove();
            });
        });
        return false;
     });

     var all_keywords_url = $('#all-keywords-url').html();
     $('.modify-subscription-keywords').click(function(evt) {
        var $this = $(this);
        var subscription_has_keywords = [];
        var html = "";
        $this.closest('.accordion-inner').find('.keyword').each(function(index, element) {
            keyword = element.textContent;
            subscription_has_keywords.push(keyword);
        });

        $.get(all_keywords_url).done(function(keywords) {
            $.each(keywords, function(index, keyword) {
                var checked = (
                    subscription_has_keywords.indexOf(keyword) != -1 ?
                    ' checked ' :
                    '');
                html += (
                    '<label class="checkbox">' +
                      '<input class="keyword-choice" type="checkbox" ' + checked + 'value="' + keyword + '"> ' + keyword +
                    '</label>');
            });
            $('#choose-keywords-list').html(html);
            var $modal = $('#choose-keywords-modal');
            $modal.data('email', $this.data('email'));
            $modal.data('package', $this.data('package'));
            $modal.data('update-id', $this.closest('.accordion-body').attr('id'));
            $('#choose-keywords-modal').modal('show');
        });
        return false;
     });

    var update_keywords_url = $('#update-keywords-url').html();
    $('#save-keywords').click(function(evt) {
        var $modal = $('#choose-keywords-modal');
        var keywords = [];
        var new_list_html = "";
        $('input.keyword-choice:checkbox:checked').each(function(i, el) {
            var keyword = el.value;
            keywords.push(keyword);
            new_list_html += (
                '<li class="keyword">' + keyword + '</li>');
        });
        $.post(update_keywords_url, {
            'package': $modal.data('package'),
            'email': $modal.data('email'),
            'keyword': keywords
        });
        $('#' + $modal.data('update-id')).find('ul').html(new_list_html);

        $modal.modal('hide');
    });
});
