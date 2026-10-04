from task import slugify
assert slugify("  Hello,   WORLD!  ")=="hello-world"
assert slugify("a___b---c")=="a-b-c"
assert slugify("***")==""
