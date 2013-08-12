$(function() {
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
            return false;
        }
        $.get(href, function(data) {
            $this.attr('data-content', data.full_description);
            $this.popover('show');
            console.debug(data);
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
});
