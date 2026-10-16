"""The one exception the commands raise for a problem the user can fix."""


class ChalkError(Exception):
    """A message for the user; the command line prints it and exits 1."""
