from pygments.lexer import RegexLexer, include, bygroups, using, this
from pygments.style import Style
from pygments.token import (
    Keyword, Name, Comment, String, Error,
    Literal, Number, Operator, Other, Punctuation, Text, Generic,
    Whitespace
)


def namedColorToHex(name: str) -> str:
    import hou

    hcolor = hou.ui.colorFromName(name)
    qcolor = hou.qt.toQColor(hcolor)
    return qcolor.name()


class VexLexer(RegexLexer):
    name = 'VEX'
    aliases = ['vex']
    filenames = ['*.vex', '*.vfl']
    mimetypes = ['application/x-vex']

    #: optional Comment or Whitespace
    _ws = r'(?:\s|//.*?\n|/[*].*?[*]/)+'

    tokens = {
        'whitespace': [
            (r'^\s*#if\s+0', Comment.Preproc, 'if0'),
            (r'^\s*#', Comment.Preproc, 'macro'),
            (r'\n', Text),
            (r'\s+', Text),
            (r'\\\n', Text),  # line continuation
            (r'//.*?\n', Comment),
            (r'/[*](.|\n)*?[*]/', Comment),
        ],
        'statements': [
            (r'"', String, 'dqstring'),
            (r'\'', String, 'sqstring'),
            (r'r"', String, 'rdqstring'),
            (r'r\'', String, 'rsqstring'),
            (r'(0x[0-9a-fA-F]|0[0-7]+|(\d+\.\d*|\.\d+)|\d+)'
             r'e[+-]\d+[lL]?', Number.Float),
            (r'0x[0-9a-fA-F]+[Ll]?', Number.Hex),
            (r'0[0-7]+[Ll]?', Number.Oct),
            (r'(\d+\.\d*|\.\d+)', Number.Float),
            (r'\d+', Number.Integer),
            (r'[~!%^&*()+=|\[\]:,.<>/?-]', Text),
            (r'(break|continue|do|else|export|forpoints|illuminance|gather|'
             r'for|foreach|if|return|while|const|_Pragma)\b', Keyword),
            (r'(int|float|vector|vector2|vector4|matrix|matrix3|string|surface|shadow|bsdf|void|lpeaccumulator)\b', Keyword.Type),
            (r'__(vex|vex_major|vex_minor)\b', Keyword.Reserved),
            (r'__(LINE|FILE|DATE|TIME)__\b', Keyword.Reserved),
            ('[a-zA-Z_][a-zA-Z0-9_]*:', Name.Label),
            ('[a-zA-Z]?@[a-zA-Z_][a-zA-Z0-9_:]*', Name.Attribute),
            ('[a-zA-Z_][a-zA-Z0-9_]*', Name),
        ],
        'root': [
            include('whitespace'),
            # functions
            (r'((?:[a-zA-Z0-9_*\s])+?(?:\s|[*]))'    # return arguments
             r'([a-zA-Z_][a-zA-Z0-9_]*)'             # method name
             r'(\s*\([^;]*?\))'                      # signature
             r'(' + _ws + r')({)',
             bygroups(using(this), Name.Function, using(this), Text, Keyword),
             'function'),
            # function declarations
            (r'((?:[a-zA-Z0-9_*\s])+?(?:\s|[*]))'    # return arguments
             r'([a-zA-Z_][a-zA-Z0-9_]*)'             # method name
             r'(\s*\([^;]*?\))'                      # signature
             r'(' + _ws + r')(;)',
             bygroups(using(this), Name.Function, using(this), Text, Text)),
            ('', Text, 'statement'),
        ],
        'statement' : [
            include('whitespace'),
            include('statements'),
            ('[{}]', Keyword),
            (';', Text, '#pop'),
        ],
        'function': [
            include('whitespace'),
            include('statements'),
            (';', Text),
            ('{', Keyword, '#push'),
            ('}', Keyword, '#pop'),
        ],
        'dqstring': [
            (r'"', String, '#pop'),
            (r'\\([\\abfnrtv"\']|x[a-fA-F0-9]{2,4}|[0-7]{1,3})', String.Escape),
            (r'[^\\"\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'sqstring': [
            (r'[\'"]', String, '#pop'),
            (r'\\([\\abfnrtv"\']|x[a-fA-F0-9]{2,4}|[0-7]{1,3})', String.Escape),
            (r'[^\\\'\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'rdqstring': [
            (r'"', String, '#pop'),
            (r'[^\\"\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'rsqstring': [
            (r'[\'"]', String, '#pop'),
            (r'[^\\\'\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'macro': [
            (r'[^/\n]+', Comment.Preproc),
            (r'/[*](.|\n)*?[*]/', Comment),
            (r'//.*?\n', Comment, '#pop'),
            (r'/', Comment.Preproc),
            (r'(?<=\\)\n', Comment.Preproc),
            (r'\n', Comment.Preproc, '#pop'),
        ],
        'if0': [
            (r'^\s*#if.*?(?<!\\)\n', Comment, '#push'),
            (r'^\s*#endif.*?(?<!\\)\n', Comment, '#pop'),
            (r'.*?\n', Comment),
        ]
    }


class OpenCLLexer(RegexLexer):
    name = 'OpenCL'
    aliases = ['ocl']
    filenames = ['*.cl']
    mimetypes = ['application/x-opencl-csrc']

    #: optional Comment or Whitespace
    _ws = r'(?:\s|//.*?\n|/[*].*?[*]/)+'

    tokens = {
        'whitespace': [
            (r'^\s*#if\s+0', Comment.Preproc, 'if0'),
            (r'^\s*#', Comment.Preproc, 'macro'),
            (r'\n', Text),
            (r'\s+', Text),
            (r'\\\n', Text),  # line continuation
            (r'//.*?\n', Comment),
            (r'/[*](.|\n)*?[*]/', Comment),
        ],
        'statements': [
            (r'"', String, 'dqstring'),
            (r'\'', String, 'sqstring'),
            (r'r"', String, 'rdqstring'),
            (r'r\'', String, 'rsqstring'),
            (r'(0x[0-9a-fA-F]|0[0-7]+|(\d+\.\d*|\.\d+)|\d+)'
             r'e[+-]\d+[lL]?', Number.Float),
            (r'0x[0-9a-fA-F]+[Ll]?', Number.Hex),
            (r'0[0-7]+[Ll]?', Number.Oct),
            (r'(\d+\.\d*|\.\d+)', Number.Float),
            (r'\d+', Number.Integer),
            (r'[~!%^&*()+=|\[\]:,.<>/?-]', Text),
            (r'(break|continue|do|else|'
             r'auto|case|char|default|enum|extern|goto|inline|register|'
             r'restrict|signed|sizeof|static|switch|typedef|union|unsigned|'
             r'void|volatile|'
             r'for|if|return|while|const|_Pragma)\b', Keyword),
            (r'(bool|char|uchar|short|ushort|'
             r'int|uint|long|ulong|exint|float|fpreal|half|'
             r'size_t|ptrdiff_t|intptr_t|uintptr_t|void|'
             r'char2|char3|char4|char8|char16|'
             r'uchar2|uchar3|uchar4|uchar8|uchar16|'
             r'short2|short3|short4|short8|short16|'
             r'ushort2|ushort3|ushort4|ushort8|ushort16|'
             r'int2|int3|int4|int8|int16|'
             r'uint2|uint3|uint4|uint8|uint16|'
             r'exint2|exint3|exint4|exint8|exint16|'
             r'long2|long3|long4|long8|long16|'
             r'ulong2|ulong3|ulong4|ulong8|ulong16|'
             r'half2|half3|half4|half8|half16|'
             r'float2|float3|float4|float8|float16|'
             r'fpreal2|fpreal3|fpreal4|fpreal8|fpreal16|'
             r'double2|double3|double4|double8|double16|'
             r'image2d_t|image3d_t|sampler_t|event_t'
             r')\b', Keyword.Type),
            (r'__(LINE|FILE|DATE|TIME)__\b', Keyword.Reserved),
            ('[a-zA-Z_][a-zA-Z0-9_]*:', Name.Label),
            ('[a-zA-Z]?@[a-zA-Z_][a-zA-Z0-9_:]*', Name.Attribute),
            ('[a-zA-Z_][a-zA-Z0-9_]*', Name),
        ],
        'root': [
            include('whitespace'),
            # functions
            (r'((?:[a-zA-Z0-9_*\s])+?(?:\s|[*]))'    # return arguments
             r'([a-zA-Z_][a-zA-Z0-9_]*)'             # method name
             r'(\s*\([^;]*?\))'                      # signature
             r'(' + _ws + r')({)',
             bygroups(using(this), Name.Function, using(this), Text, Keyword),
             'function'),
            # function declarations
            (r'((?:[a-zA-Z0-9_*\s])+?(?:\s|[*]))'    # return arguments
             r'([a-zA-Z_][a-zA-Z0-9_]*)'             # method name
             r'(\s*\([^;]*?\))'                      # signature
             r'(' + _ws + r')(;)',
             bygroups(using(this), Name.Function, using(this), Text, Text)),
            ('', Text, 'statement'),
        ],
        'statement' : [
            include('whitespace'),
            include('statements'),
            ('[{}]', Keyword),
            (';', Text, '#pop'),
        ],
        'function': [
            include('whitespace'),
            include('statements'),
            (';', Text),
            ('{', Keyword, '#push'),
            ('}', Keyword, '#pop'),
        ],
        'dqstring': [
            (r'"', String, '#pop'),
            (r'\\([\\abfnrtv"\']|x[a-fA-F0-9]{2,4}|[0-7]{1,3})', String.Escape),
            (r'[^\\"\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'sqstring': [
            (r'[\'"]', String, '#pop'),
            (r'\\([\\abfnrtv"\']|x[a-fA-F0-9]{2,4}|[0-7]{1,3})', String.Escape),
            (r'[^\\\'\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'rdqstring': [
            (r'"', String, '#pop'),
            (r'[^\\"\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'rsqstring': [
            (r'[\'"]', String, '#pop'),
            (r'[^\\\'\n]+', String), # all other characters
            (r'\\\n', String), # line continuation
            (r'\\', String), # stray backslash
        ],
        'macro': [
            (r'[^/\n]+', Comment.Preproc),
            (r'/[*](.|\n)*?[*]/', Comment),
            (r'//.*?\n', Comment, '#pop'),
            (r'/', Comment.Preproc),
            (r'(?<=\\)\n', Comment.Preproc),
            (r'\n', Comment.Preproc, '#pop'),
        ],
        'if0': [
            (r'^\s*#if.*?(?<!\\)\n', Comment, '#push'),
            (r'^\s*#endif.*?(?<!\\)\n', Comment, '#pop'),
            (r'.*?\n', Comment),
        ]
    }


class HScriptLexer(RegexLexer):
    name = 'HScript'
    aliases = ['hscript', 'Hscript']
    filenames = ['*.cmd']
    mimetypes = ['application/x-hscript']

    tokens = {'root': [
            (r'\b(set|if|then|else|endif|for|to|step|foreach|while|end|'
             r'break|continue)\s*\b',
             Keyword),
        
            (r'^\s*([A-Za-z][A-Za-z0-9_]+)\s*\b',
             Name.Builtin),
             
            (r'\s(-[A-Za-z][A-Za-z0-9_]*)', Operator.Word),
             
            (r'#.*\n', Comment),
            
            (r'(\b\w+\s*)(=)', bygroups(Name.Variable, Operator)),
            (r'[\[\]{}\(\)=]+', Operator),
            (r'(==|!=|<|>|<=|>=|&&|\|\|)', Operator),
            
            (r'\$\(', Keyword, 'paren'),
            (r'\${', Keyword, 'curly'),
            (r'`.+`', String.Backtick),
            (r'(\d+\.)?(\d+)(?= |\Z)', Number),
            (r'\$#?(\w+|.)', Name.Variable),
            (r'"(\\\\|\\[0-7]+|\\.|[^"])*"', String.Double),
            (r"'(\\\\|\\[0-7]+|\\.|[^'])*'", String.Single),
            (r'\s+', Text),
            (r'[^=\s\n]+', Text),
        ],
        'curly': [
            (r'}', Keyword, '#pop'),
            (r':-', Keyword),
            (r'[^}:]+', Punctuation),
            (r':', Punctuation),
        ],
        'paren': [
            (r'\)', Keyword, '#pop'),
            (r'[^)]*', Punctuation),
        ],
    }
    

# class HoudiniStyle(Style):
#     background_color = namedColorToHex("TextboxBG")
#     default_style = ""
#
#     # ParmSyntaxPlainColor:  #EDEFF5
#     # ParmSyntaxStringColor:  #88C0D0
#     # ParmSyntaxVarColor:  #D08770
#     # ParmSyntaxFuncColor:  #A3BE8C
#     # ParmSyntaxKeywordColor:  #B48FAD
#     # ParmSyntaxQuoteColor:  #81A1C1
#     # ParmSyntaxNumberColor:  #8FBCBB
#     # ParmSyntaxRefColor:  #EBCB8B
#     # ParmSyntaxCommentColor:  #5E81AC
#     # ParmSyntaxErrorColor:  #BF616A
#     # ParmParenMatchColor:  #88C0D0
#     # ParmQuoteMatchColor:  #88C0D0
#     # ParmMisMatchColor:  #979797
#
#     styles = {
#         Text: namedColorToHex("TextColor"),
#         # Whitespace: "#f8f8f2",
#
#         Comment: namedColorToHex("ParmSyntaxCommentColor"),
#         # Comment.Hashbang: "#6272a4",
#         # Comment.Multiline: "#6272a4",
#         # Comment.Preproc: "#ff79c6",
#         # Comment.Single: "#6272a4",
#         # Comment.Special: "#6272a4",
#
#         Generic: "#ff00ff",  # namedColorToHex("ParmSyntaxPlainColor"),
#         # Generic.Deleted: "#8b080b",
#         # Generic.Emph: "#f8f8f2 underline",
#         Generic.Error: namedColorToHex("ParmSyntaxErrorColor"),
#         # Generic.Heading: "#f8f8f2 bold",
#         # Generic.Inserted: "#f8f8f2 bold",
#         # Generic.Output: "#44475a",
#         # Generic.Prompt: "#f8f8f2",
#         # Generic.Strong: "#f8f8f2",
#         # Generic.Subheading: "#f8f8f2 bold",
#         # Generic.Traceback: "#f8f8f2",
#
#         Error: namedColorToHex("ParmSyntaxErrorColor"),
#
#         Keyword: namedColorToHex("ParmSyntaxKeywordColor"),
#         # Keyword.Constant: "#ff79c6",
#         # Keyword.Declaration: "#8be9fd italic",
#         # Keyword.Namespace: "#ff79c6",
#         # Keyword.Pseudo: "#ff79c6",
#         # Keyword.Reserved: "#ff79c6",
#         # Keyword.Type: "#8be9fd",
#
#         Literal: namedColorToHex("ParmSyntaxRefColor"),
#         # Literal.Date: "#f8f8f2",
#
#         Name: namedColorToHex("TextColor"),
#         # Name.Attribute: "#50fa7b",
#         # Name.Builtin: "#8be9fd italic",
#         # Name.Builtin.Pseudo: "#f8f8f2",
#         # Name.Class: "#50fa7b",
#         # Name.Constant: "#f8f8f2",
#         # Name.Decorator: "#f8f8f2",
#         # Name.Entity: "#f8f8f2",
#         # Name.Exception: "#f8f8f2",
#         Name.Function: namedColorToHex("ParmSyntaxFuncColor"),
#         # Name.Label: "#8be9fd italic",
#         # Name.Namespace: "#f8f8f2",
#         # Name.Other: "#f8f8f2",
#         # Name.Tag: "#ff79c6",
#         Name.Variable: namedColorToHex("ParmSyntaxVarColor"),
#         # Name.Variable.Class: "#8be9fd italic",
#         # Name.Variable.Global: "#8be9fd italic",
#         # Name.Variable.Instance: "#8be9fd italic",
#
#         Number: namedColorToHex("ParmSyntaxNumberColor"),
#         # Number.Bin: "#bd93f9",
#         # Number.Float: "#bd93f9",
#         # Number.Hex: "#bd93f9",
#         # Number.Integer: "#bd93f9",
#         # Number.Integer.Long: "#bd93f9",
#         # Number.Oct: "#bd93f9",
#
#         Operator: namedColorToHex("TextColor"),
#         # Operator.Word: "#ff79c6",
#
#         Other: "#ff9900",
#
#         Punctuation: namedColorToHex("TextColor"),
#
#         String: namedColorToHex("ParmSyntaxStringColor"),
#         # String.Backtick: "#f1fa8c",
#         # String.Char: "#f1fa8c",
#         # String.Doc: "#f1fa8c",
#         # String.Double: "#f1fa8c",
#         # String.Escape: "#f1fa8c",
#         # String.Heredoc: "#f1fa8c",
#         # String.Interpol: "#f1fa8c",
#         # String.Other: "#f1fa8c",
#         # String.Regex: "#f1fa8c",
#         # String.Single: "#f1fa8c",
#         # String.Symbol: "#f1fa8c",
#     }

