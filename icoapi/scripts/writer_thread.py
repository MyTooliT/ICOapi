"""Write a measurement bundle in a thread of its own

A measurement receives data from all units in one event loop. Writing the data
to disk must not hold the loop up: A disk that is slow for a moment (a virus
scanner that looks at the new file, a USB drive, a full cache) would stop all
streams, and the CAN adapters have buffers of limited size.

:class:`ThreadedBundleWriter` has the interface of the ``BundleWriter`` of
ICOschema, but a thread owns the file (h5py objects are not made for several
threads) and does all the writing:

- Rows are collected in blocks of ``block_rows`` rows by the caller. Full
  blocks are handed to the writer thread through a queue.
- The queue has a limit. If the disk is so slow that the limit is reached, the
  next row raises a :class:`WriterError`: A measurement that fails clearly is
  better than one that uses more and more memory and loses data later.
- If the writer thread fails (e.g. the disk is full), the next row, flush or
  close raises a :class:`WriterError` with the reason.
- ``close`` waits until everything that was handed over is written.
"""

# -- Imports ------------------------------------------------------------------

from collections.abc import Sequence
import logging
from queue import Empty, Full, Queue
import threading
from time import monotonic
from types import TracebackType
from typing import Any, Self

from icoschema.v2 import BundleWriter, Provenance, SourceSpec
import numpy as np

# -- Globals ------------------------------------------------------------------

logger = logging.getLogger(__name__)

DEFAULT_BLOCK_ROWS = 2048
"""Number of rows that are handed to the writer thread at once"""

DEFAULT_QUEUE_BLOCKS = 256
"""Number of blocks that can wait for the writer thread

With 2048 rows this is more than 2 minutes of the data of a unit that sends
3000 rows per second.
"""

FLUSH_INTERVAL = 5.0
"""Seconds between the times the writer thread flushes the file to disk"""

TIMEOUT = 120.0
"""Seconds to wait for the writer thread (to open the file, to finish)"""

# -- Classes ------------------------------------------------------------------


class WriterError(RuntimeError):
    """The data could not be written"""


class _Stop:  # pylint: disable=too-few-public-methods
    """Marker: Everything is handed over, finish the file"""


class ThreadedSource:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Collect the rows of a source and hand them to the writer thread

    Has the interface of the ``SourceWriter`` of ICOschema that is used to
    record a measurement (``append_row`` and ``update``). Use it from the
    thread that created the writer only.
    """

    def __init__(
        self,
        writer: "ThreadedBundleWriter",
        spec: SourceSpec,
        block_rows: int,
    ) -> None:
        self.name = str(spec.name)
        self._writer = writer
        self._channels = len(spec.channels)
        self._has_counter = spec.has_counter
        self._block_rows = block_rows
        self._dtype = np.dtype(
            ([("counter", "u1")] if spec.has_counter else [])
            + [("timestamp", "<u8")]
            + [(f"c{number}", "<f4") for number in range(self._channels)]
        )
        self._block = np.zeros(block_rows, dtype=self._dtype)
        self._filled = 0

    def append_row(
        self,
        timestamp: int,
        values: Sequence[float],
        counter: int | None = None,
    ) -> None:
        """Add one row (see ``SourceWriter.append_row``)

        Raises:

            WriterError: If the writer thread failed or can not keep up

        """

        if len(values) != self._channels:
            raise ValueError(
                f"source {self.name!r} has {self._channels} channels, got"
                f" {len(values)} values"
            )
        row = self._block[self._filled]
        if self._has_counter:
            if counter is None:
                raise ValueError(
                    f"source {self.name!r} has a packet counter: pass"
                    " `counter`"
                )
            row["counter"] = counter
        row["timestamp"] = timestamp
        for number, value in enumerate(values):
            row[f"c{number}"] = value
        self._filled += 1
        if self._filled == self._block_rows:
            self.hand_over()

    def append_rows(
        self,
        timestamps: np.ndarray,
        values: np.ndarray,
        counters: np.ndarray | None = None,
    ) -> None:
        """Add many rows at once

        Args:

            timestamps:
                The timestamps of the rows (shape ``(rows,)``)

            values:
                The values of the rows (shape ``(rows, channels)``)

            counters:
                The packet counters of the rows (shape ``(rows,)``). Needed
                if the source has a packet counter.

        Raises:

            WriterError: If the writer thread failed or can not keep up

        """

        rows = len(timestamps)
        if values.shape != (rows, self._channels):
            raise ValueError(
                f"source {self.name!r} has {self._channels} channels, got"
                f" values with shape {values.shape} for {rows} rows"
            )
        if self._has_counter and counters is None:
            raise ValueError(
                f"source {self.name!r} has a packet counter: pass `counters`"
            )

        start = 0
        while start < rows:
            end = min(rows, start + self._block_rows - self._filled)
            target = slice(self._filled, self._filled + end - start)
            if self._has_counter:
                assert counters is not None
                self._block["counter"][target] = counters[start:end]
            self._block["timestamp"][target] = timestamps[start:end]
            for number in range(self._channels):
                self._block[f"c{number}"][target] = values[start:end, number]
            self._filled += end - start
            start = end
            if self._filled == self._block_rows:
                self.hand_over()

    def update(self, **values: Any) -> None:
        """Change attributes of the source (see ``SourceWriter.update``)"""

        self._writer.command(("update", self.name, values))

    def hand_over(self) -> None:
        """Hand over the rows that were collected to the writer thread"""

        if not self._filled:
            return
        block = self._block[: self._filled]
        # The thread uses the block: Continue with a new one
        self._block = np.zeros(self._block_rows, dtype=self._dtype)
        self._filled = 0
        self._writer.command(("rows", self.name, block), blocks=True)

    def write_block(self, writer: BundleWriter, block: np.ndarray) -> None:
        """Write a block to the file (runs in the writer thread)"""

        writer[self.name].append(
            block["timestamp"],
            np.column_stack([
                block[f"c{number}"] for number in range(self._channels)
            ]),
            block["counter"] if self._has_counter else None,
        )


class ThreadedBundleWriter:  # pylint: disable=too-many-instance-attributes
    """Write a bundle (like ``BundleWriter``) with a thread of its own

    Args:

        path:
            The path of the file

        sources:
            The sources of the bundle

        provenance:
            Where the data comes from (optional)

        block_rows:
            The number of rows that are handed to the writer thread at once

        queue_blocks:
            The number of blocks that may wait for the writer thread

    Raises:

        Everything the ``BundleWriter`` raises, if the file can not be created

    """

    # pylint: disable-next=too-many-arguments
    def __init__(
        self,
        path: str,
        sources: Sequence[SourceSpec],
        *,
        provenance: Provenance | None = None,
        block_rows: int = DEFAULT_BLOCK_ROWS,
        queue_blocks: int = DEFAULT_QUEUE_BLOCKS,
    ) -> None:
        self.path = str(path)
        self._queue: Queue[Any] = Queue(maxsize=queue_blocks)
        self._error: BaseException | None = None
        self._opened = threading.Event()
        self._open_error: BaseException | None = None
        self._closed = False
        self._sources = {
            str(spec.name): ThreadedSource(self, spec, block_rows)
            for spec in sources
        }
        self._thread = threading.Thread(
            target=self._run,
            args=(list(sources), provenance),
            name=f"writer {self.path}",
            daemon=True,
        )
        self._thread.start()
        if not self._opened.wait(TIMEOUT):
            raise WriterError(f"Could not create file “{self.path}” in time")
        if self._open_error is not None:
            self._thread.join()
            raise self._open_error

    # -- Thread -----------------------------------------------------------

    def _run(
        self, sources: list[SourceSpec], provenance: Provenance | None
    ) -> None:
        """Write everything that is handed over (the writer thread)"""

        try:
            writer = BundleWriter(self.path, sources, provenance=provenance)
        except BaseException as error:  # pylint: disable=broad-exception-caught
            self._open_error = error
            self._opened.set()
            return
        self._opened.set()

        last_flush = monotonic()
        try:
            while True:
                try:
                    # Wait until the next flush is due
                    item = self._queue.get(
                        timeout=max(
                            0.0, FLUSH_INTERVAL - (monotonic() - last_flush)
                        )
                    )
                except Empty:
                    item = None
                if isinstance(item, _Stop):
                    break
                if item is not None and self._error is None:
                    try:
                        self._handle(writer, item)
                    except BaseException as error:  # pylint: disable=broad-exception-caught
                        logger.exception("Cannot write to “%s”", self.path)
                        self._error = error
                elif item is not None and item[0] == "flush":
                    item[1].set()  # Do not keep anyone waiting after a failure
                if monotonic() - last_flush >= FLUSH_INTERVAL:
                    last_flush = monotonic()
                    if self._error is None:
                        try:
                            writer.flush()
                        except BaseException as error:  # pylint: disable=broad-exception-caught
                            self._error = error
        finally:
            try:
                writer.close()
            except BaseException as error:  # pylint: disable=broad-exception-caught
                self._error = self._error or error

    def _handle(self, writer: BundleWriter, item: tuple) -> None:
        """Do what was handed over (runs in the writer thread)"""

        kind = item[0]
        if kind == "rows":
            self._sources[item[1]].write_block(writer, item[2])
        elif kind == "update":
            writer[item[1]].update(**item[2])
        elif kind == "picture":
            writer.add_picture(item[1], item[2])
        elif kind == "flush":
            writer.flush()
            item[1].set()

    # -- Caller -------------------------------------------------------------

    def _raise_error(self) -> None:
        """Raise the error of the writer thread (if there is one)"""

        if isinstance(self._error, WriterError):
            raise self._error
        if self._error is not None:
            raise WriterError(
                f"Cannot write to “{self.path}”: {self._error}"
            ) from self._error

    def command(self, item: tuple, *, blocks: bool = False) -> None:
        """Hand something over to the writer thread

        Args:

            item:
                What should be done

            blocks:
                The item is a block of rows. A block is refused, if the
                writer thread does not keep up (all other items wait).

        Raises:

            WriterError:
                If the writer thread failed, is closed or does not keep up

        """

        self._raise_error()
        if self._closed:
            raise WriterError("The writer is closed")
        try:
            if blocks:
                self._queue.put_nowait(item)
            else:
                self._queue.put(item, timeout=TIMEOUT)
        except Full as error:
            # Data was lost: Writing is not possible any more
            failure = WriterError(
                f"The disk is too slow: {self._queue.maxsize} blocks of data"
                f" wait to be written to “{self.path}”"
            )
            failure.__cause__ = error
            self._error = failure
            raise failure from error

    def __getitem__(self, name: str) -> ThreadedSource:
        return self._sources[name]

    @property
    def sources(self) -> dict[str, ThreadedSource]:
        """The sources of the bundle"""

        return dict(self._sources)

    def add_picture(self, name: str, images: list[str]) -> None:
        """Add pictures (see ``BundleWriter.add_picture``)"""

        self.command(("picture", name, list(images)))

    def flush(self) -> None:
        """Wait until everything that was added is written to the file

        Raises:

            WriterError: If something could not be written

        """

        for source in self._sources.values():
            source.hand_over()
        done = threading.Event()
        self.command(("flush", done))
        if not done.wait(TIMEOUT):
            raise WriterError(f"Writing to “{self.path}” takes too long")
        self._raise_error()

    def close(self) -> None:
        """Write everything and close the file (closing twice is fine)

        Raises:

            WriterError: If something could not be written

        """

        if self._closed:
            return
        try:
            for source in self._sources.values():
                source.hand_over()
        except WriterError:
            # Close what is there; the error is raised below
            pass
        self._closed = True
        try:
            self._queue.put(_Stop(), timeout=TIMEOUT)
        except Full:
            logger.error("Cannot finish “%s”: The queue is full", self.path)
        self._thread.join(TIMEOUT)
        if self._thread.is_alive():
            raise WriterError(f"Writing to “{self.path}” takes too long")
        self._raise_error()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
