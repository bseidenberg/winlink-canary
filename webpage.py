'''
Generate a wepage the displays a table with node status.
'''
from datetime import datetime

def generate_html(node_status, title="Node Status Dashboard"):
    '''Generate an HTML status page based on an array of status dicts.'''
    html = """<!DOCTYPE html>
    <html lang="en">
    <head>
        <title>{title}</title>
        <meta http-equiv="refresh" content="900">
        <style>
            body {{ font-family: sans-serif; }}
            table {{ border-collapse: collapse; width: 60%; margin: 20px auto; }}
            th, td {{ padding: 10px; text-align: center; border: 1px solid #ddd; }}
            th {{ background-color: #f4f4f4; }}
            .status-indicator {{ display: inline-block; width: 15px; height: 15px; border-radius: 50%; }}
            .healthy {{ background-color: green; }}
            .pending {{ background-color: grey; }}
            .unhealthy {{ background-color: red; }}
        </style>
    </head>
    <body>
        <h2 style="text-align: center;">{title}</h2>
        <table>
            <tr>
                <th>Node Name</th>
                <th>Frequency</th>
                <th>Status</th>
                <th>Last Healthy</th>
            </tr>
    """.format(title=title)

    for node in node_status:
        status_class = {
            "HEALTHY": "healthy",
            "UNHEALTHY": "unhealthy",
            "PENDING": "pending"
        }.get(node["state"], "pending")
        last_tested = ('Never' if node['last_healthy'] == 0 else
                       datetime.fromtimestamp(node['last_healthy']).strftime('%Y-%m-%d %H:%M'))

        html += """
            <tr>
                <td>{name}</td>
                <td>{frequency:.3f}</td>
                <td>
                    <span class="status-indicator {status_class}"></span>
                    {status_text}
                </td>
                <td>{last_tested}</td>
            </tr>
        """.format(name=node['name'], frequency=node["frequency"], status_class=status_class,
                   status_text=node['state'], last_tested=last_tested)

    html += """
        </table>
    </body>
    </html>"""

    return html

# Example status array for testing
sample_node_status = [
    {"name": "NodeA", "frequency": 440.35, "state": "HEALTHY", "last_healthy": 1714060800},
    {"name": "NodeB", "frequency": 430.850, "state": "UNHEALTHY", "last_healthy": 1714064400},
    {"name": "NodeC", "frequency": 439.750, "state": "PENDING", "last_healthy": 1714068000},
    {"name": "NodeD", "frequency": 439.85, "state": "HEALTHY", "last_healthy": 1714089000}
]

def main():
    '''Generate HTML output for testing.'''
    html_content = generate_html(sample_node_status, '')
    with open("node_status.html", "w", encoding="utf-8") as f:
        f.write(html_content)


if __name__ == "__main__":
    main()
