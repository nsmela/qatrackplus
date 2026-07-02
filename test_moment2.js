const moment = require('./qatrack/static/moment/moment.min.js');
console.log(moment("02 Jul 2026 10:58", ["DD MMM YYYY HH:mm", "YYYY-MM-DD HH:mm"], true).toDate());
console.log(moment("2026-07-02 10:58", ["DD MMM YYYY HH:mm", "YYYY-MM-DD HH:mm"], true).toDate());
