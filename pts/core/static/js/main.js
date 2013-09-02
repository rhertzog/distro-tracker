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


    $('#subscribe-button').click(function(evt) {
        evt.preventDefault();
        var $this = $(this);

        /**
         * Function takes an email and subscribes it to the current package.
         */
        var subscribe_function = function(email) {
            $.post($this.data('subscribe'), {
                'package': $this.data('package'),
                'email': email
            }).done(function(data) {
                // Replace the subscribe button with an unsubscribe button
                $this.parents('div.btn-group').hide();
                $('#unsubscribe-button').parents('div.btn-group').show();
            })
        };

        // Get all the emails of the user.
        $.get($this.data('get-emails')).done(function(data) {
            if (data.length === 1) {
                // Go ahead and subscribe the user since there is only one email
                return subscribe_function(data[0])
            } else {
                // Ask the user to choose which email(s) should be subscribed
                // to the package.
            }
        });
    });
});
