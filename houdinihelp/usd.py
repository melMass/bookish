from pygments.lexer import RegexLexer
from pygments.token import *


class UsdLexer(RegexLexer):
    name = 'USD'
    aliases = ['usd', 'usda']
    filenames = ['*.usd', '*.usda']
    mimetypes = ['application/x-usd']

    tokens = {
        "root": [
            (r"#sdf.*?\n", Comment.Special),
            (r"#usda.*?\n", Comment.Special),

            (r"\s+", Whitespace),
            (r"[()\[\]{}]+", Punctuation),
            (r"//.*?\n", Comment.Single),
            (r"(/[*].*?[*]/)+", Comment.Multiline),
            ('"""', String.Doc, "triple_string"),
            ('"', String.Double, "string"),
            ("@", String.Other, "asset_path"),
            (r"</", String.Other, "prim_path"),

            (r"\b(class|def|over|variant|variantSets|dictionary|timeSamples|clips|variantSet)\b",
             Keyword.Declaration),
            (r"\b(add|delete|reorder)\b", Keyword.Constant),
            (r"\b(inherits|references|variants|payload|subLayers)\b",
             Keyword.Type),
            (r"\b(bool|uchar|int|uint|half|quat|float|double|string|token|asset|color|point|normal|frame|vector|matrix)[0-9]?[0-9]?(d)?(f)?(\[\])?\b",
             Keyword.Type),

            (r"[=,]", Operator),

            (r"\b(kind|defaultPrim|upAxis|startTimeCode|endTimeCode|instanceable|hidden|active)\b",
             Operator.Word),
            (r"\b(uniform|custom)\b",
             Operator.Word),

            (r"(?<=\W)(-)?[0-9]+(\.[0-9]*)?(?=\W)", Number),
            (r"\w+:", Name.Variable),
            (r"\w+", Name),
        ],
        "string": [
            (r'[^\\"\n]+', String.Double),
            (r'"', String.Double, '#pop'),
            (r'\\.', String.Double),
            (r'[$\n]', Error, '#pop'),
        ],
        "triple_string": [
            (r'[^\\"]+', String.Doc),
            (r"\\.", String.Escape),
            ('"""', String.Doc, "#pop"),
            (r'"', String.Doc),
        ],
        "asset_path": [
            (r"[^@]+", String.Other),
            ("@", String.Other, "#pop"),
        ],
        "prim_path": [
            (r"[^>]+", String.Other),
            (">", String.Other, "#pop"),
        ]
    }


