from django.core.mail import EmailMessage
from email.mime.base import MIMEBase
import copy


class CustomEmailMessage(EmailMessage):
    """
    A subclass of ``django.core.mail.EmailMessage`` which allows users to use
    an ``email.message.Message`` instance to define the body of the message.

    If ``msg`` is set, the ``body`` attribute is ignored.

    If the user wants to attach additional parts to the message, the ``attach``
    method can be used but the user must ensure that the given ``msg`` instance
    is a multipart message.

    Effectively, this is also a wrapper which allows sending instances of
    ``email.message.Message`` via Django email backends.
    """
    def __init__(self, msg=None, *args, **kwargs):
        """
        Use the keyword argument ``msg`` to set the ``email.message.Message``
        instance which should be used to define the body of the message.
        The original object is copied.

        If no ``msg`` is set, the object's behaviour is identical to
        ``EmailMessage``.
        """
        EmailMessage.__init__(self, *args, **kwargs)
        self.msg = msg

    def message(self):
        if self.msg:
            msg = self._attach_all()
            return msg
        else:
            return EmailMessage.message(self)

    def _attach_all(self):
        """
        Attaches all existing attachments to the given message ``msg``.
        """
        msg = self.msg
        if self.attachments:
            assert self.msg.is_multipart()
            msg = copy.deepcopy(self.msg)
            for attachment in self.attachments:
                if isinstance(attachment, MIMEBase):
                    msg.attach(attachment)
                else:
                    msg.attach(self._create_attachment(*attachment))
        return msg
