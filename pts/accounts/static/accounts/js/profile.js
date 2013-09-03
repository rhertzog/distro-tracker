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
});
