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

    $('.has-tooltip').tooltip();
});
