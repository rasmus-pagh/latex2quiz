#!/usr/bin/env python3
"""Compatibility facade and executable entry point for the implementation package."""

from __future__ import annotations

from latex2quiz_lib.model import (
    ConversionError,
    Answer,
    Question,
    WrittenSubquestion,
    WrittenSection,
    RenderRequest,
    RenderedImage,
)

from latex2quiz_lib.source import (
    DEFAULT_PREAMBLE,
    MACRO_ALIASES,
    _line_number,
    strip_comments,
    _command_pattern,
    _stray_item,
    _balanced_group,
    _remove_group_command,
    _command_definition_spans,
    _remove_command_definitions,
    _clean_fragment,
    _extract_points,
    _clean_written_fragment,
    _written_stem,
    _points_from_section_title,
    parse_questions,
    parse_written_sections,
    _extract_preamble,
    _extract_body_command_definitions,
)

from latex2quiz_lib.alttext import (
    _LATEX_UNICODE_SYMBOLS,
    _LATEX_WORD_OPERATORS,
    _LATEX_WRAPPERS,
    _LATEX_DECLARATIONS,
    _LATEX_ALGORITHM_WORDS,
    _SUPERSCRIPT,
    _SUBSCRIPT,
    _LatexUnicodeParser,
    latex_to_plain,
)

from latex2quiz_lib.render import (
    _render_document,
    _png_dimensions,
    document_preamble,
    render_document_source,
    render_resolutions,
    store_rendered_pages,
    render_failure_message,
    render_latex,
)

from latex2quiz_lib.qti import (
    QTI_NS,
    IMSCP_NS,
    XSI_NS,
    XML_NS,
    LOM_NS,
    QTI_SCHEMA,
    PACKAGE_SCHEMA,
    _qti,
    _imscp,
    _number,
    _split_mapping_total,
    _effective_points,
    _has_percentage,
    mc_title_latex,
    mc_title,
    _mc_instruction,
    _mc_stem_latex,
    heading_latex,
    _add_image,
    build_item_xml,
    build_written_item_xml,
    build_manifest,
)

from latex2quiz_lib.htmltext import (
    _PAR,
    _BLOCK_START,
    _BLOCK_END,
    _MARKERS,
    _MATH_ENVIRONMENTS,
    _ALIGNED_BLOCKS,
    _DRAWINGS,
    _HEADINGS,
    IMAGE_ENVIRONMENT,
    _LIST_ENVIRONMENTS,
    _VERBATIM_ENVIRONMENTS,
    _FONTS,
    _TRANSPARENT,
    _NEUTRAL_DECLARATIONS,
    _SILENT_WITH_ARGUMENTS,
    _PARAGRAPH_BREAKS,
    _LINE_BREAKS,
    _SPACES,
    _SYMBOLS,
    _KEYWORDS,
    _ACCENTS,
    _MATH_RENAMES,
    _MATH_DROPS,
    _MACRO_PATTERN,
    _MATH_GROUP_FONTS,
    _MATH_GROUP_FONT_PATTERN,
    Macro,
    STRUCTURAL_MACROS,
    extract_macros,
    _read_argument,
    expand_macros,
    _image_tag,
    _clean_math,
    _assemble,
    _wrap,
    section_labels,
    HtmlConverter,
    _Parser,
    _split_items,
    figure_latex,
    latex_to_html,
    unwrap_paragraph,
)

from latex2quiz_lib.learnosity import (
    AUTHOR_VERSION,
    CREATED_BY,
    ESSAY_MAX_LENGTH,
    MC_QUESTION_NAME,
    ESSAY_QUESTION_NAME,
    Number,
    JsonObject,
    SCORE_DECIMALS,
    _score,
    _reference,
    _item,
    build_mc_item,
    load_essay_template,
    _essay_question,
    section_points,
    part_points,
    build_written_item,
    build_written_parts_item,
    build_bank,
    _walk_keys,
    compare_keys,
    _is_number,
    validate_bank,
    _validate_mcq,
    item_maximum_scores,
)

from latex2quiz_lib.package import (
    _write_xml,
    _zip_tree,
    _verify_package_tree,
    _package_identifier,
    _written_feedback_latex,
    _render_requests,
    _html_fragments,
    _figure_key,
    _figure_requests,
    _fragment_html,
    build_learnosity_bank,
    _write_json,
    convert,
)

from latex2quiz_lib.pdf import (
    PDF_LABELS,
    _LATEX_SPECIALS,
    _latex_escape,
    _labels,
    pdf_output_paths,
    _mc_page,
    _written_page,
    pdf_document_source,
    compile_pdf,
    convert_pdf,
)

from latex2quiz_lib.cli import (
    _parser,
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())

