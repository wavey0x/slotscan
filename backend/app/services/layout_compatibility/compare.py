"""Pure directional compatibility rules."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from math import ceil

from app.services.compiled_layout import CompiledLayout
from app.services.layout_compatibility.models import (
    ComparisonEntry,
    ComparisonImpact,
    ComparisonLocation,
    ComparisonRegion,
    ComparisonResult,
    ComparisonSummary,
    ComparisonType,
    ComparisonVerdict,
)
from app.services.layout_compatibility.normalize import (
    LayoutNormalizationUnavailable,
    LayoutNormalizer,
    NormalizedLayout,
    NormalizedRegion,
    NormalizedScope,
    PhysicalShape,
    ShapeMember,
)


DETAILS = {
    "unchanged": "The physical location and recursive storage shape are unchanged.",
    "name_changed": "The physical shape is unchanged, but the declared name changes.",
    "nominal_type_changed": (
        "The physical shape is unchanged, but the nominal type label changes."
    ),
    "shape_changed": "The declared physical storage shape changes.",
    "moved": "An existing declaration is physically relocated.",
    "removed": "An occupied From declaration is missing from To.",
    "overlap": "The To declaration overlaps an occupied From region.",
    "addition": "The To declaration occupies storage not used by From.",
    "inserted": (
        "The To declaration uses an unlabeled hole before the end of From storage."
    ),
    "scope_added": "To adds a disjoint exact storage scope.",
    "scope_removed": "An exact From storage scope is missing from To.",
    "scope_root_changed": "The exact storage scope root changes.",
    "scope_label_changed": (
        "The proven scope root and physical tree are unchanged, but its identifier changes."
    ),
    "mapping_key_changed": "The mapping key encoding changes.",
    "array_rule_changed": "Array element packing or stride changes.",
    "array_reduced": "The fixed array length is reduced.",
    "array_extended": "The fixed array is extended without relocating its prefix.",
    "gap_consumed": "New whole-slot declarations consume a prefix of a recognized gap.",
    "gap_ambiguous": "The recognized storage gap is consumed or reshaped ambiguously.",
}


class _AnalysisLimit(RuntimeError):
    pass


def _overlaps(first: NormalizedRegion, second: NormalizedRegion) -> bool:
    first_location = first.report.location
    second_location = second.report.location
    if (
        first_location.end_slot < second_location.slot
        or second_location.end_slot < first_location.slot
    ):
        return False
    if (
        first_location.slot == first_location.end_slot
        == second_location.slot
        == second_location.end_slot
    ):
        first_end = first_location.byte_offset + first_location.byte_size
        second_end = second_location.byte_offset + second_location.byte_size
        return (
            first_location.byte_offset < second_end
            and second_location.byte_offset < first_end
        )
    return True


class LayoutComparator:
    """Compare two exact layouts without chain or address context."""

    def __init__(
        self,
        *,
        normalizer: LayoutNormalizer | None = None,
        max_entries: int = 2000,
        max_details_per_entry: int = 8,
        max_detail_length: int = 500,
    ):
        self.normalizer = normalizer or LayoutNormalizer()
        self.max_entries = max_entries
        self.max_details_per_entry = max_details_per_entry
        self.max_detail_length = max_detail_length
        self._entries: list[ComparisonEntry] = []

    def compare(
        self,
        from_layout: CompiledLayout,
        to_layout: CompiledLayout,
    ) -> ComparisonResult:
        try:
            normalized_from = self.normalizer.normalize(from_layout)
            normalized_to = self.normalizer.normalize(to_layout)
        except LayoutNormalizationUnavailable as exc:
            return ComparisonResult(
                verdict=ComparisonVerdict.UNAVAILABLE,
                summary=None,
                entries=(),
                limitations=(exc.code,),
            )
        return self.compare_normalized(normalized_from, normalized_to)

    def compare_normalized(
        self,
        normalized_from: NormalizedLayout,
        normalized_to: NormalizedLayout,
    ) -> ComparisonResult:
        """Compare already-normalized layouts without chain or I/O context."""
        try:
            self._entries = []
            self._compare_layouts(normalized_from, normalized_to)
            entries = tuple(sorted(self._entries, key=self._entry_sort_key))
        except _AnalysisLimit:
            return ComparisonResult(
                verdict=ComparisonVerdict.UNAVAILABLE,
                summary=None,
                entries=(),
                limitations=("analysis_limit",),
            )

        conflicts = sum(
            entry.impact is ComparisonImpact.CONFLICT for entry in entries
        )
        ambiguous = sum(
            entry.impact is ComparisonImpact.AMBIGUOUS for entry in entries
        )
        unchanged = sum(entry.kind == "unchanged" for entry in entries)
        changes = sum(
            entry.impact is ComparisonImpact.NONE and entry.kind != "unchanged"
            for entry in entries
        )
        if conflicts:
            verdict = ComparisonVerdict.CONFLICTS
        elif ambiguous:
            verdict = ComparisonVerdict.INDETERMINATE
        else:
            verdict = ComparisonVerdict.NO_CONFLICTS
        return ComparisonResult(
            verdict=verdict,
            summary=ComparisonSummary(
                conflicts=conflicts,
                ambiguous=ambiguous,
                changes=changes,
                unchanged=unchanged,
            ),
            entries=entries,
        )

    def _compare_layouts(
        self,
        from_layout: NormalizedLayout,
        to_layout: NormalizedLayout,
    ) -> None:
        unmatched_to = list(to_layout.scopes)
        for from_scope in from_layout.scopes:
            to_scope = self._matching_scope(from_scope, unmatched_to)
            if to_scope is None:
                for region in from_scope.regions:
                    self._emit(
                        "scope_removed",
                        ComparisonImpact.CONFLICT,
                        region,
                        None,
                    )
                continue
            unmatched_to.remove(to_scope)
            if from_scope.report.root_slot != to_scope.report.root_slot:
                self._compare_changed_scope_root(from_scope, to_scope)
            else:
                if (
                    from_scope.report.kind == "erc7201"
                    and from_scope.report.id != to_scope.report.id
                    and self._scope_physical_key(from_scope)
                    == self._scope_physical_key(to_scope)
                ):
                    for from_region, to_region in zip(
                        from_scope.regions,
                        to_scope.regions,
                        strict=True,
                    ):
                        self._emit(
                            "scope_label_changed",
                            ComparisonImpact.AMBIGUOUS,
                            from_region,
                            to_region,
                        )
                else:
                    self._compare_scope(from_scope, to_scope)
        for to_scope in unmatched_to:
            for region in to_scope.regions:
                self._emit(
                    "scope_added",
                    ComparisonImpact.NONE,
                    None,
                    region,
                )

    @staticmethod
    def _matching_scope(
        from_scope: NormalizedScope,
        candidates: list[NormalizedScope],
    ) -> NormalizedScope | None:
        if from_scope.report.kind == "default":
            return next(
                (
                    scope
                    for scope in candidates
                    if scope.report.kind == "default"
                ),
                None,
            )
        same_root = next(
            (
                scope
                for scope in candidates
                if scope.report.kind == "erc7201"
                and scope.report.root_slot == from_scope.report.root_slot
            ),
            None,
        )
        if same_root:
            return same_root
        return next(
            (
                scope
                for scope in candidates
                if scope.report.kind == "erc7201"
                and scope.report.formula == from_scope.report.formula
            ),
            None,
        )

    @staticmethod
    def _scope_physical_key(scope: NormalizedScope) -> tuple:
        return tuple(
            (
                region.report.location.slot - scope.report.root_slot,
                region.report.location.byte_offset,
                region.shape.physical_key(),
            )
            for region in scope.regions
        )

    def _compare_changed_scope_root(
        self,
        from_scope: NormalizedScope,
        to_scope: NormalizedScope,
    ) -> None:
        unmatched_to = list(to_scope.regions)
        for from_region in from_scope.regions:
            to_region = next(
                (
                    region
                    for region in unmatched_to
                    if region.report.path == from_region.report.path
                ),
                unmatched_to[0] if unmatched_to else None,
            )
            if to_region:
                unmatched_to.remove(to_region)
            self._emit(
                "scope_root_changed",
                ComparisonImpact.CONFLICT,
                from_region,
                to_region,
            )
        for to_region in unmatched_to:
            self._emit(
                "scope_root_changed",
                ComparisonImpact.CONFLICT,
                None,
                to_region,
            )

    def _compare_scope(
        self,
        from_scope: NormalizedScope,
        to_scope: NormalizedScope,
    ) -> None:
        handled_from, handled_to = self._compare_storage_gaps(
            from_scope,
            to_scope,
        )
        from_regions = [
            region
            for region in from_scope.regions
            if region.report.identity() not in handled_from
        ]
        to_regions = [
            region
            for region in to_scope.regions
            if region.report.identity() not in handled_to
        ]
        unmatched_to = list(to_regions)
        max_from_end = max(
            (
                region.end_slot
                for region in from_regions
                if not self._is_gap(region)
            ),
            default=from_scope.report.root_slot - 1,
        )
        for from_region in from_regions:
            exact = next(
                (
                    region
                    for region in unmatched_to
                    if region.start == from_region.start
                ),
                None,
            )
            if exact:
                unmatched_to.remove(exact)
                self._compare_region(
                    from_region,
                    exact,
                    from_regions=from_regions,
                )
                continue
            same_name = next(
                (
                    region
                    for region in unmatched_to
                    if region.report.path == from_region.report.path
                ),
                None,
            )
            if same_name:
                unmatched_to.remove(same_name)
                self._emit(
                    "moved",
                    ComparisonImpact.CONFLICT,
                    from_region,
                    same_name,
                )
                continue
            overlap = next(
                (
                    region
                    for region in unmatched_to
                    if _overlaps(from_region, region)
                ),
                None,
            )
            if overlap:
                unmatched_to.remove(overlap)
                self._emit(
                    "overlap",
                    ComparisonImpact.CONFLICT,
                    from_region,
                    overlap,
                )
                continue
            self._emit(
                "removed",
                ComparisonImpact.CONFLICT,
                from_region,
                None,
            )

        for to_region in unmatched_to:
            overlapping_from = next(
                (
                    region
                    for region in from_regions
                    if _overlaps(region, to_region) and not self._is_gap(region)
                ),
                None,
            )
            if overlapping_from:
                self._emit(
                    "overlap",
                    ComparisonImpact.CONFLICT,
                    overlapping_from,
                    to_region,
                )
            elif (
                from_scope.report.kind != "default"
                or to_region.report.location.slot > max_from_end
            ):
                self._emit(
                    "addition",
                    ComparisonImpact.NONE,
                    None,
                    to_region,
                )
            else:
                self._emit(
                    "inserted",
                    ComparisonImpact.AMBIGUOUS,
                    None,
                    to_region,
                )

    @staticmethod
    def _is_gap(region: NormalizedRegion) -> bool:
        return (
            (
                region.report.path == "__gap"
                or region.report.path.startswith("__gap_")
            )
            and region.shape.kind == "fixed_array"
            and region.shape.element is not None
            and region.shape.element.byte_size == 32
            and region.shape.elements_per_slot == 1
        )

    def _compare_storage_gaps(
        self,
        from_scope: NormalizedScope,
        to_scope: NormalizedScope,
    ) -> tuple[set[str], set[str]]:
        handled_from: set[str] = set()
        handled_to: set[str] = set()
        for from_gap in filter(self._is_gap, from_scope.regions):
            start = from_gap.report.location.slot
            end = from_gap.report.location.end_slot + 1
            inside = [
                region
                for region in to_scope.regions
                if start <= region.report.location.slot < end
            ]
            unchanged = next(
                (
                    region
                    for region in inside
                    if self._is_gap(region)
                    and region.report.location.slot == start
                    and region.report.location.end_slot + 1 == end
                ),
                None,
            )
            if unchanged and len(inside) == 1:
                continue

            remaining_gap = next(
                (
                    region
                    for region in inside
                    if self._is_gap(region)
                    and region.report.location.end_slot + 1 == end
                ),
                None,
            )
            additions = sorted(
                (
                    region
                    for region in inside
                    if region is not remaining_gap and not self._is_gap(region)
                ),
                key=lambda region: region.start,
            )
            cursor = start
            valid = bool(additions)
            for addition in additions:
                location = addition.report.location
                whole_slots = (
                    location.byte_offset == 0
                    and location.byte_size % 32 == 0
                    and location.slot == cursor
                )
                if not whole_slots:
                    valid = False
                    break
                cursor = location.end_slot + 1
            if remaining_gap and remaining_gap.report.location.slot != cursor:
                valid = False
            if not remaining_gap and cursor != end:
                valid = False

            handled_from.add(from_gap.report.identity())
            handled_to.update(region.report.identity() for region in inside)
            if valid:
                for addition in additions:
                    self._emit(
                        "gap_consumed",
                        ComparisonImpact.NONE,
                        None,
                        addition,
                    )
            else:
                self._emit(
                    "gap_ambiguous",
                    ComparisonImpact.AMBIGUOUS,
                    from_gap,
                    inside[0] if inside else None,
                )
        return handled_from, handled_to

    def _compare_region(
        self,
        from_region: NormalizedRegion,
        to_region: NormalizedRegion,
        *,
        from_regions: list[NormalizedRegion],
    ) -> None:
        from_shape = from_region.shape
        to_shape = to_region.shape
        if from_shape.physical_key() == to_shape.physical_key():
            if from_region.report.path != to_region.report.path:
                self._emit(
                    "name_changed",
                    ComparisonImpact.AMBIGUOUS,
                    from_region,
                    to_region,
                )
            elif from_shape.label != to_shape.label:
                self._emit(
                    "nominal_type_changed",
                    ComparisonImpact.AMBIGUOUS,
                    from_region,
                    to_region,
                )
            else:
                self._emit(
                    "unchanged",
                    ComparisonImpact.NONE,
                    from_region,
                    to_region,
                )
            return
        if from_shape.kind != to_shape.kind or from_shape.encoding != to_shape.encoding:
            self._emit(
                "shape_changed",
                ComparisonImpact.CONFLICT,
                from_region,
                to_region,
            )
            return
        if from_shape.kind == "mapping":
            if (
                not from_shape.key
                or not to_shape.key
                or from_shape.key.mapping_key_key()
                != to_shape.key.mapping_key_key()
            ):
                self._emit(
                    "mapping_key_changed",
                    ComparisonImpact.CONFLICT,
                    from_region,
                    to_region,
                )
                return
            self._compare_symbolic_child(
                from_region,
                to_region,
                from_shape.value,
                to_shape.value,
                "[value]",
                from_regions,
            )
            return
        if from_shape.kind == "dynamic_array":
            if (
                from_shape.element_stride != to_shape.element_stride
                or from_shape.elements_per_slot != to_shape.elements_per_slot
            ):
                self._emit(
                    "array_rule_changed",
                    ComparisonImpact.CONFLICT,
                    from_region,
                    to_region,
                )
                return
            self._compare_symbolic_child(
                from_region,
                to_region,
                from_shape.element,
                to_shape.element,
                "[]",
                from_regions,
            )
            return
        if from_shape.kind == "fixed_array":
            if (
                from_shape.element_stride != to_shape.element_stride
                or from_shape.elements_per_slot != to_shape.elements_per_slot
            ):
                self._emit(
                    "array_rule_changed",
                    ComparisonImpact.CONFLICT,
                    from_region,
                    to_region,
                )
            elif (
                not from_shape.element
                or not to_shape.element
                or from_shape.element.physical_key()
                != to_shape.element.physical_key()
            ):
                self._emit(
                    "shape_changed",
                    ComparisonImpact.CONFLICT,
                    from_region,
                    to_region,
                )
            elif (to_shape.array_length or 0) < (from_shape.array_length or 0):
                self._emit(
                    "array_reduced",
                    ComparisonImpact.CONFLICT,
                    from_region,
                    to_region,
                )
            elif (to_shape.array_length or 0) > (from_shape.array_length or 0):
                extension_overlaps = any(
                    region is not from_region
                    and region.report.location.slot
                    <= to_region.report.location.end_slot
                    and region.report.location.end_slot
                    > from_region.report.location.end_slot
                    for region in from_regions
                )
                self._emit(
                    "array_extended",
                    (
                        ComparisonImpact.CONFLICT
                        if extension_overlaps
                        else ComparisonImpact.NONE
                    ),
                    from_region,
                    to_region,
                    extra_details=(
                        ("The extended range overlaps a later From declaration.",)
                        if extension_overlaps
                        else ()
                    ),
                )
            else:
                self._compare_symbolic_child(
                    from_region,
                    to_region,
                    from_shape.element,
                    to_shape.element,
                    "[]",
                    from_regions,
                )
            return
        if from_shape.kind == "struct":
            self._compare_members(
                from_region,
                to_region,
                from_shape.members,
                to_shape.members,
                from_regions,
            )
            return
        self._emit(
            "shape_changed",
            ComparisonImpact.CONFLICT,
            from_region,
            to_region,
        )

    def _compare_symbolic_child(
        self,
        from_parent: NormalizedRegion,
        to_parent: NormalizedRegion,
        from_shape: PhysicalShape | None,
        to_shape: PhysicalShape | None,
        path_suffix: str,
        from_regions: list[NormalizedRegion],
    ) -> None:
        if not from_shape or not to_shape:
            self._emit(
                "shape_changed",
                ComparisonImpact.CONFLICT,
                from_parent,
                to_parent,
            )
            return
        self._compare_region(
            self._child_region(
                from_parent,
                from_shape,
                path=f"{from_parent.report.path}{path_suffix}",
            ),
            self._child_region(
                to_parent,
                to_shape,
                path=f"{to_parent.report.path}{path_suffix}",
            ),
            from_regions=from_regions,
        )

    def _compare_members(
        self,
        from_parent: NormalizedRegion,
        to_parent: NormalizedRegion,
        from_members: tuple[ShapeMember, ...],
        to_members: tuple[ShapeMember, ...],
        from_regions: list[NormalizedRegion],
    ) -> None:
        unmatched_to = list(to_members)
        for from_member in from_members:
            to_member = next(
                (
                    member
                    for member in unmatched_to
                    if (
                        member.slot,
                        member.byte_offset,
                    )
                    == (
                        from_member.slot,
                        from_member.byte_offset,
                    )
                ),
                None,
            )
            from_child = self._member_region(from_parent, from_member)
            if to_member is None:
                same_name = next(
                    (
                        member
                        for member in unmatched_to
                        if member.name == from_member.name
                    ),
                    None,
                )
                if same_name:
                    unmatched_to.remove(same_name)
                    self._emit(
                        "moved",
                        ComparisonImpact.CONFLICT,
                        from_child,
                        self._member_region(to_parent, same_name),
                    )
                else:
                    self._emit(
                        "removed",
                        ComparisonImpact.CONFLICT,
                        from_child,
                        None,
                    )
                continue
            unmatched_to.remove(to_member)
            self._compare_region(
                from_child,
                self._member_region(to_parent, to_member),
                from_regions=from_regions,
            )
        max_from_slot = max(
            (
                member.slot
                + max(1, ceil(member.byte_size / 32))
                - 1
                for member in from_members
            ),
            default=-1,
        )
        for to_member in unmatched_to:
            to_child = self._member_region(to_parent, to_member)
            if to_member.slot > max_from_slot:
                self._emit(
                    "addition",
                    ComparisonImpact.NONE,
                    None,
                    to_child,
                )
            else:
                self._emit(
                    "inserted",
                    ComparisonImpact.AMBIGUOUS,
                    None,
                    to_child,
                )

    def _member_region(
        self,
        parent: NormalizedRegion,
        member: ShapeMember,
    ) -> NormalizedRegion:
        slot = parent.report.location.slot + member.slot
        end_slot = slot + max(
            1,
            ceil((member.byte_offset + member.byte_size) / 32),
        ) - 1
        return NormalizedRegion(
            report=ComparisonRegion(
                scope=parent.report.scope,
                location=ComparisonLocation(
                    slot=slot,
                    byte_offset=member.byte_offset,
                    byte_size=member.byte_size,
                    end_slot=end_slot,
                    is_root=member.shape.encoding
                    in {"mapping", "dynamic_array"},
                ),
                path=f"{parent.report.path}.{member.name}",
                type=ComparisonType(
                    label=member.shape.label,
                    kind=member.shape.kind,
                    encoding=member.shape.encoding,
                    byte_size=member.shape.byte_size,
                    array_length=member.shape.array_length,
                    element_stride=member.shape.element_stride,
                ),
            ),
            shape=member.shape,
        )

    def _child_region(
        self,
        parent: NormalizedRegion,
        shape: PhysicalShape,
        *,
        path: str,
    ) -> NormalizedRegion:
        return NormalizedRegion(
            report=replace(
                parent.report,
                path=path,
                type=ComparisonType(
                    label=shape.label,
                    kind=shape.kind,
                    encoding=shape.encoding,
                    byte_size=shape.byte_size,
                    array_length=shape.array_length,
                    element_stride=shape.element_stride,
                ),
            ),
            shape=shape,
        )

    def _emit(
        self,
        kind: str,
        impact: ComparisonImpact,
        from_region: NormalizedRegion | None,
        to_region: NormalizedRegion | None,
        *,
        extra_details: tuple[str, ...] = (),
    ) -> None:
        details = (DETAILS[kind],) + extra_details
        if (
            len(details) > self.max_details_per_entry
            or any(len(detail) > self.max_detail_length for detail in details)
        ):
            raise _AnalysisLimit
        from_report = from_region.report if from_region else None
        to_report = to_region.report if to_region else None
        identity = "|".join(
            (
                kind,
                from_report.identity() if from_report else "-",
                to_report.identity() if to_report else "-",
            )
        )
        entry_id = "cmp:" + sha256(identity.encode()).hexdigest()[:24]
        if any(entry.id == entry_id for entry in self._entries):
            return
        self._entries.append(
            ComparisonEntry(
                id=entry_id,
                impact=impact,
                kind=kind,
                from_region=from_report,
                to_region=to_report,
                details=details,
            )
        )
        if len(self._entries) > self.max_entries:
            raise _AnalysisLimit

    @staticmethod
    def _entry_sort_key(entry: ComparisonEntry) -> tuple:
        region = entry.from_region or entry.to_region
        if region is None:
            return ("", 0, 0, entry.id)
        return (
            region.scope.id,
            region.location.slot,
            region.location.byte_offset,
            entry.id,
        )
