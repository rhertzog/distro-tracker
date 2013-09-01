$(function() {
    /**
     * Any links found in the accordion header (package subscription list)
     * should work as links, not as a details toggle.
     */
     $('.accordion-toggle a').click(function(evt) {
        evt.stopPropagation();
     })
});