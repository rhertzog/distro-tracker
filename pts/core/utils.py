def get_or_none(model, **kwargs):
    """
    Gets a Django Model object from the database or returns None if it
    does not exist.
    """
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None
