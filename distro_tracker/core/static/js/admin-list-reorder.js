// @license magnet:?xt=urn:btih:cf05388f2679ee054f2beb29a391d25f4e673ac3&dn=gpl-2.0.txt GPL-2.0-or-later
$(document).ready(function() {
    // Set this to the name of the column holding the position
    pos_field = 'position';
    // Determine the column number of the position field
    pos_col = null;
    cols = $('#result_list tbody tr:first').children();

    for (i = 0; i < cols.length; i++) {
        inputs = $(cols[i]).find('input[name*=' + pos_field + ']');

        if (inputs.length > 0) {
            // Found!
            pos_col = i;
            break;
        }
    }

    if (pos_col == null) {
        return;
    }

    // Hide position field
    $header = $($('#result_list thead tr').children()[pos_col]);
    $header.hide();
    $('#result_list tbody tr').each(function(index) {
        $($(this).children()[pos_col]).hide();
    });

    // Determine sorted column and order
    sorted = $('#result_list thead th.sorted');
    sorted_col = $('#result_list thead th').index(sorted);
    sort_order = sorted.hasClass('descending') ? 'desc' : 'asc';

    if (sorted_col != pos_col) {
        // Sorted column is not position column, bail out
        console.info("Sorted column is not %s, bailing out", pos_field);
        return;
    }

    $('#result_list tbody tr').css('cursor', 'move');

    // Make tbody > tr sortable
    $('#result_list tbody').sortable({
        axis: 'y',
        items: 'tr',
        cursor: 'move',
        update: function(event, ui) {
            item = ui.item;
            items = $(this).find('tr').get();
            if (sort_order == 'desc') {
                // Reverse order
                items.reverse();
            }

            $(items).each(function(index) {
                pos_td = $(this).children()[pos_col];
                input = $(pos_td).children('input').first();
                label = $(pos_td).children('strong').first();

                input.attr('value', index + 1);
                label.text(index);
            });

            // Update row classes
            $(this).find('tr').removeClass('row1').removeClass('row2');
            $(this).find('tr:even').addClass('row1');
            $(this).find('tr:odd').addClass('row2');
        }
    });

    $('#content h1').after(
        "<div>You can drag and drop repositories in the list below to modify their order.</div>" +
        "<div>Don't forget to click save when you're done.</div>"
    );
});
// @license-end
