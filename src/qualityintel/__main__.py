"""Allows ``python -m qualityintel``, which works even when the ``qi`` script is not on PATH."""

from qualityintel.cli import main

raise SystemExit(main())
