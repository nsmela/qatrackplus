import os

base_dir = r"c:\Users\nsmel\source\repos\qatrackplus\qatrack\qa"
css_path = os.path.join(base_dir, "static", "qa", "css", "testlist.css")
js_path = os.path.join(base_dir, "static", "qa", "js", "testlist.js")
template_path = os.path.join(base_dir, "templates", "admin", "qa", "testlist", "change_list.html")
change_form_path = os.path.join(base_dir, "templates", "admin", "qa", "testlist", "change_form.html")

with open(css_path, encoding="utf-8") as f:
    css_content = f.read()

with open(js_path, encoding="utf-8") as f:
    js_content = f.read()

include_path = os.path.join(base_dir, "templates", "admin", "qa", "testlist", "testlist_assets.html")
with open(include_path, "w", encoding="utf-8") as f:
    f.write("<style>\n")
    f.write(css_content)
    f.write("\n</style>\n<script>\n")
    f.write(js_content)
    f.write("\n</script>\n")

# Update change_list.html
with open(template_path, encoding="utf-8") as f:
    cl_content = f.read()

if "{% include 'admin/qa/testlist/testlist_assets.html' %}" not in cl_content:
    cl_content = cl_content.replace("{% block content_title %}", "{% block content_title %}\n    {% include 'admin/qa/testlist/testlist_assets.html' %}")
    with open(template_path, "w", encoding="utf-8") as f:
        f.write(cl_content)

# Update change_form.html
with open(change_form_path, encoding="utf-8") as f:
    cf_content = f.read()
    
if "{% include 'admin/qa/testlist/testlist_assets.html' %}" not in cf_content:
    cf_content = cf_content.replace("{% block content %}", "{% block content %}\n    {% include 'admin/qa/testlist/testlist_assets.html' %}")
    with open(change_form_path, "w", encoding="utf-8") as f:
        f.write(cf_content)

print("Assets inlined successfully.")
