$(function() {
    /**
     * Any links found in the accordion header (package subscription list)
     * should work as links, not as a details toggle.
     */
     $('.accordion-toggle a').click(function(evt) {
        evt.stopPropagation();
     });

     var unsubscribe_url = $('#unsubscribe-url').html();

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
                    $group.parent().remove();
                } else {
                    $group.remove();
                }
            });
        });
        return false;
     });
});
