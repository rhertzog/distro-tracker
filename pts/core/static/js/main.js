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
