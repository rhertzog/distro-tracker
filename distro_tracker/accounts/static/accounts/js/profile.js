// @license magnet:?xt=urn:btih:cf05388f2679ee054f2beb29a391d25f4e673ac3&dn=gpl-2.0.txt GPL-2.0-or-later
$(function() {
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
            var to_remove = $group.find('.accordion-group.subscription-group');
            $this.fadeOut();

            to_remove.fadeOut(500, function() {
                if ($group.find('.team-group').length === 0) {
                    to_remove.parent().before('<em>No subscriptions!</em>');
                    to_remove.parent().remove();
                }
            });
        });
        return false;
     });

     var all_keywords_url = $('#all-keywords-url').html();

     /**
      * Shows a popup with options to modify keywords. It works for both user
      * default keywords and subscription-specific keywords.
      */
     var modify_keywords_popup = function(button, modify_options) {

        var subscription_has_keywords = [];
        var html = "";
        var existing_keywords = $(button.data('details')).find('.keyword');
        existing_keywords.each(function(index, element) {
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
                    '<div class="checkbox"><label>' +
                      '<input class="keyword-choice" type="checkbox" ' + checked + 'value="' + keyword + '"> ' + keyword +
                    '</label></div>');
            });
            $('#choose-keywords-list').html(html);

            var $modal = $('#choose-keywords-modal');
            var data_to_forward = ['email', 'package', 'details', 'href'];
            data_to_forward.forEach(function(key) {
                if (button.data(key)) {
                    $modal.data(key, button.data(key));
                } else {
                    $modal.removeData(key);
                }
            });
            $modal.modal('show');
        });
    };

    $('.modify-keywords').click(function(evt) {
        var $this = $(this);
        modify_keywords_popup($this);
        return false;
    });

    var update_subscription_keywords_url = $('#update-keywords-url').html();
    $('#save-keywords').click(function(evt) {
        var $modal = $('#choose-keywords-modal');
        var update_keywords_url = (
            $modal.data('href') !== undefined ?
            $modal.data('href') :
            update_subscription_keywords_url)
        var keywords = [];
        var new_list_html = "";
        $('input.keyword-choice:checkbox:checked').each(function(i, el) {
            var keyword = el.value;
            keywords.push(keyword);
            new_list_html += (
                '<span class="keyword label label-primary m-l-1">' + keyword + '</span> ');
        });
        $.post(update_keywords_url, {
            'package': $modal.data('package'),
            'email': $modal.data('email'),
            'keyword': keywords
        });
        $($modal.data('details')).find('.keyword-list').html(new_list_html);

        $modal.modal('hide');
    });

    $('.toggle-team-mute').click(function(evt) {
        $(this).closest('form').submit();
        return false;
    });

    $('#package-subscribe-form').submit(function(){
        /* First check that the textbox is filled */
        var input = $("#package-subscribe-form input[name='package']");
        var form_group = input.parents('.form-group').first();
        var pkg_name = $.trim(input.val());
        if (pkg_name === '') {
            form_group.addClass('has-danger');
            input.addClass('form-control-danger');
            var helper = $('<span class="text-help">').text('This field is required.');
            input.parent().append(helper);
            return false;
        }
        /* Then check that at least one email is selected */
        var any_email_checked = false;
        $("input[type='checkbox'][name='email']").each(function(){
            if($(this).prop('checked')) any_email_checked = true;
        });
        if(!any_email_checked){
            $("#dt-subscription-email-list").parents('.form-group').addClass('has-danger');
            var helper = $('<div class="text-help">').text('You need to select at least an email to subscribe.');
            $("#dt-subscription-email-list").append(helper);
            return false;
        }
    });
    $("input[type='checkbox'][name='email']").change(function(){
        if(this.checked) {
            $("#dt-subscription-email-list").parents('.form-group').removeClass('has-danger');
            if ($("#dt-subscription-email-list").children('.text-help').length) {
                $("#dt-subscription-email-list").children('.text-help').remove();
            }
        }
    });
});
// @license-end
