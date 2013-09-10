$(function() {
    function csrfSafeMethod(method) {
        // these HTTP methods do not require CSRF protection
        return (/^(GET|HEAD|OPTIONS|TRACE)$/.test(method));
    }
    $.ajaxSetup({
        crossDomain: false, // obviates need for sameOrigin test
        beforeSend: function(xhr, settings) {
            if (!csrfSafeMethod(settings.type)) {
                xhr.setRequestHeader("X-CSRFToken", $.cookie('csrftoken'));
            }
        }
    });

    $('#package-search-input').typeahead([
        {
            name: 'source-packages',
            remote: '/api/package/search/autocomplete?q=%QUERY&package_type=source',
            header: '<h5 class="text-center typeahead-package-title">Source packages</h5>',
            // Use a slightly larger delay between requests than the default
            rateLimitWait: 500
        },
        {
            name: 'pseudo-packages',
            remote: '/api/package/search/autocomplete?q=%QUERY&package_type=pseudo',
            header: '<h5 class="text-center typeahead-package-title">Pseudo Packages</h5>',
            // Use a slightly larger delay between requests than the default
            rateLimitWait: 500
        }
    ]);

    $('.has-tooltip').tooltip({
        'delay': {
            'show': 500,
            'hide': 50
        }
    });

    /**
     * Activate popovers for action needed items. They show the full
     * description of the item.
     */
    $('.has-popover.action-needed-details').popover({
        html: true
    });
    /**
     * Asynchronously retrieve full descriptions of action needed items.
     */
    $('.has-popover.action-needed-details').click(function(evt) {
        evt.preventDefault();
        var $this = $(this);
        // Retrieve the content only if it hasn't already been retrieved
        if ($this.attr('data-content') !== undefined) {
            return;
        }
        // The url is given in the href data attribute.
        var href = $this.attr('data-href');
        if (href === undefined) {
            return;
        }
        $.get(href, function(data) {
            // Build the meta data based on the response
            var meta_data = "<div>Severity: " + data.severity.name + "</div>";
            meta_data += "<div>Created: " + data.created + "</div>";
            meta_data += "<div>Last Updated: " + data.updated + "</div>";
            // Meta data goes into the title
            $this.attr('data-original-title', meta_data);
            // The content is the description
            $this.attr('data-content', data.full_description);
            $this.popover('show');
        })
    });
    /**
     * Dismiss popovers when a user clicks anywhere outside of them.
     */
    $('body').on('click', function (e) {
        $('.has-popover').each(function () {
            if (!$(this).is(e.target) && $(this).has(e.target).length === 0 && $('.popover').has(e.target).length === 0) {
                $(this).popover('hide');
            }
        });
    });

    // Activate scrolling for divs. Lets us have a visually nicer scroll bar
    // in a cross-browser compatible way for panels with
    $('.scrollable').each(function(index) {
        var $this = $(this);
        // Hack to allow using max-height for without height in the CSS.
        $this.height($this.height() + 1);
        // On mobile the overflow is set to auto and we want to let the browser
        // handle the scrolling for us.
        if ($this.css('overflow') !== 'auto') {
            $this.perfectScrollbar();
        }
    });

    var subscribe_url = $('#subscribe-button').data('url');
    var unsubscribe_url = $('#unsubscribe-button').data('url')
    var toggle_subscription_buttons = function() {
        $('#subscribe-button').parents('div.btn-group').toggle();
        $('#unsubscribe-button').parents('div.btn-group').toggle();
    }
    /**
     * Function subscribes the user with the given email to the given package.
     */
    var subscribe_user_to_package = function(email, package_name) {
        $.post(subscribe_url, {
            'package': package_name,
            'email': email
        }).done(function(data) {
            // Replace the subscribe button with an unsubscribe button
            toggle_subscription_buttons()
        })
    };

    var unsubscribe_user_from_package = function(package_name) {
        $.post(unsubscribe_url, {
            'package': package_name
        }).done(function(data) {
            toggle_subscription_buttons()
        });
    };

    var email_chosen_handler = function(evt) {
        var $this = $(this);
        subscribe_user_to_package($this.data('email'), $this.data('package'));
        $('#choose-email-modal').modal('hide');
    };

    $('#subscribe-button').click(function(evt) {
        evt.preventDefault();
        var $this = $(this);

        // Get all the emails of the user.
        $.get($this.data('get-emails')).done(function(data) {
            if (data.length === 1) {
                // Go ahead and subscribe the user since there is only one email
                return subscribe_user_to_package(data[0], $this.data('package'));
            } else {
                // Ask the user to choose which email(s) should be subscribed
                // to the package.
                var package_name = $this.data('package');
                var html = ""
                for (var i = 0; i < data.length; ++i) {
                    var email = data[i]
                    html += (
                        '<button class="btn subscribe-select-email" id="choose-email-' + i + '"' +
                        ' data-email="' + email + '" data-package="' + package_name + '">' + email +
                        '</button>'
                    );
                }
                $('#choose-email-modal .modal-body').html(html);
                // Attach a click handler to the created buttons
                $('.subscribe-select-email').click(email_chosen_handler);
                $('#choose-email-modal').modal('show');
            }
        });
    });

    $('#unsubscribe-button').click(function(evt) {
        evt.preventDefault();
        unsubscribe_user_from_package($(this).data('package'));
    });

    $('#delete-team-button').click(function(evt) {
        $('#confirm-team-delete-modal').modal('show');
        return false;
    });

});
