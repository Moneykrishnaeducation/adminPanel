from rest_framework.permissions import IsAuthenticated
"""Package initializer for adminPanel.views

Avoid importing submodules here to prevent circular import issues during
URL resolver startup. Individual view modules should be imported directly
where needed (for example, in `adminPanel.urls`).

Expose a small __all__ so tools and linters that import the package
don't accidentally execute view code.
"""

__all__ = []