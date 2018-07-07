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

    var sourcePackages = new Bloodhound({
	datumTokenizer: Bloodhound.tokenizers.obj.whitespace('value'),
	queryTokenizer: Bloodhound.tokenizers.whitespace,
	remote: {
	    url: '/api/package/search/autocomplete?q=%QUERY&package_type=source',
	    wildcard: '%QUERY',
	    rateLimitWait: 500,
	    transform: function(r) { return r[1]; }
	}
    });
    var binaryPackages = new Bloodhound({
	datumTokenizer: Bloodhound.tokenizers.obj.whitespace('value'),
	queryTokenizer: Bloodhound.tokenizers.whitespace,
	remote: {
	    url: '/api/package/search/autocomplete?q=%QUERY&package_type=binary',
	    wildcard: '%QUERY',
	    rateLimitWait: 500,
	    transform: function(r) { return r[1]; }
	}
    });
    var pseudoPackages = new Bloodhound({
	datumTokenizer: Bloodhound.tokenizers.obj.whitespace('value'),
	queryTokenizer: Bloodhound.tokenizers.whitespace,
	remote: {
	    url: '/api/package/search/autocomplete?q=%QUERY&package_type=pseudo',
	    wildcard: '%QUERY',
	    rateLimitWait: 500,
	    transform: function(r) { return r[1]; }
	}
    });

    $('.package-completion').typeahead({
	hint: false,
	highlight: true,
	minLength: 2
    },
    {
	name: 'source-packages',
	source: sourcePackages,
	templates: {
	    header: '<h5 class="text-center typeahead-package-title">Source packages</h5>'
	}
    },
    {
	name: 'binary-packages',
	source: binaryPackages,
	templates: {
	    header: '<h5 class="text-center typeahead-package-title">Binary packages</h5>'
	}
    },
    {
	name: 'pseudo-packages',
	source: pseudoPackages,
	templates: {
	    header: '<h5 class="text-center typeahead-package-title">Pseudo Packages</h5>'
	}
    }
    );

    var teams = new Bloodhound({
      datumTokenizer: function(data) {
        Bloodhound.tokenizers.obj.whitespace(data.slug);
      },
      queryTokenizer: Bloodhound.tokenizers.whitespace,
      remote: {
        url: '/api/teams/search/autocomplete?q=%QUERY',
        wildcard: '%QUERY',
        rateLimitWait: 500,
        transform: function(r) {
          return r['teams'];
        }
      }
    });

    $('.team-completion').typeahead({
        hint: false,
        highlight: true,
        minLength: 2
      },
      {
        name: 'teams',
        displayKey: 'slug',
        source: teams,
        templates: {
        suggestion: function (teams) {
            return '<p>' + teams.name + '</p>';
          }
        }
      }
    ).bind('typeahead:render', function(e) {
      var options = $('div.tt-dataset-teams p');
      if(options.length == 1){
        options.first().addClass('tt-cursor');
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
                        '<button class="btn btn-primary m-r-1 subscribe-select-email" id="choose-email-' + i + '"' +
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

    $('.remove-package-from-team-button').click(function(evt) {
        // Set which package should be removed upon clicking the confirmation
        // button.
        var $this = $(this);
        var $modal = $('#confirm-package-remove-modal');
        var package_to_remove = $modal.find('#remove-package-name');
        package_to_remove.val($this.data('package'))

        // It is safe to display the popup now.
        $modal.modal('show');
        return false;
    });

    /**
     * Automatically provide a team slug in the form after a name has been entered.
     * This is done only for the team creation form, so as to make sure the user
     * changes an existing team's slug deliberately.
     */
    $('#create-team-form #id_name').blur(function() {
        var $this = $(this);
        var name = $this.val();
        var slug = name.toLowerCase()
                       .replace(/[^-\w ]+/g, '')
                       .replace(/ +/g, '-');
        var $form = $this.parents('form');
	if (!$form.find('#id_slug').val()) {
	    $form.find('#id_slug').val(slug);
	}
    });

    $('.toggle-package-mute').click(function(evt) {
        $(this).closest('form').submit();
        return false;
    });

  $(".popover-hover").popover({
    trigger: "manual",
    html: true,
    animation: true
  }).on("mouseenter", function () {
    var _this = this;
    $(this).popover("show");
    $(".popover").on("mouseleave", function () {
      $(_this).popover('hide');
    });
  }).on("mouseleave", function () {
    var _this = this;
    setTimeout(function () {
      if (!$(".popover:hover").length) {
        $(_this).popover("hide");
      }
    }, 100);
  });
});
