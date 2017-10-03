ourApp.config(['$translateProvider', function ($translateProvider) {
    $translateProvider.useSanitizeValueStrategy(null);
    $translateProvider.translations('en', {
        'TAGLINE': 'File sync for the office that is backed by <strong>Subversion</strong>, with revision history, permissions, and built for multiple users',
        'FOOTER': '&copy; 2016, 2017 <b>Paul Hammant</b>. All Rights Reserved',
        'KNOW_MORE': 'MORE INFO?',
        'FEATURES': 'Features',
        'LIST': 'Basic file-sync features',
        'FILE_TYPES': 'Large and small file types',
        'ALL_SORTS': 'Excel Spreadsheets, Word documents, Powerpoint presentation, etc. Movies, music, picts too.',
        'DIRECT': 'Users can setup file sync for a subdirectory of a larger tree',
        'RW_PERMS': 'Multi-user with read and write permissions',
        'RW_PERMS2': 'Permissions can be set at any place in the directory tree for users and groups',
        'SVN': 'Using Subversion means many features come by default',
        'HIST': 'Terabytes of revision history is permanently retained',
        'HIST2': 'Subversion does not have an upper limit of what can be stored in it',
        'POWER_USERS': 'Power users can still use traditional Svn workflows',
        'CLI_TOOLS': 'Like &apos;checkout&apos; and &apos;commit&apos;, as well as batch operations',
        'STILL_READING': 'Less main stream features',
        'X_PLAT': 'Works on Windows, Mac and Linux',
        'EXCEPT': 'Not for iOS or Android, yet',
        'PYTHON': 'Simple Python client (and three Python packages) is the entire installation',
        'NO_SVN': 'No client-side installation of Subversion at all means no &apos;working copy&apos; or .svn folders (or duplicated files)',
        'EXCLUDES': 'Files can be globally excluded from sync operations via their suffix',
        'EXCLUDES2': 'Some applications make a temp backup file while editing, like &apos;.bak&apos;',
        'TESTIMONIALS': 'Testimonials from those using it',
        'TESTIMONIAL_1': 'I have been using this for a year and love it. It is just what I have always wanted',
        'PH': 'Paul Hammant',
        'TESTIMONIAL_2': 'I hope he is going to stop talking about it soon',
        'PH_FRIEND': 'Paul&apos;s friend',
        'GH': 'is open source <a href="https://github.com/paul-hammant/subsyncit">on GitHub</a> (of course). Installation instructions <a href="https://github.com/paul-hammant/subsyncit/blob/master/CLIENT-SETUP.md">here</a>.'
    });

    $translateProvider.translations('es', {
        'TAGLINE': 'File sync for the office that is backed by <strong>Subversion</strong>, with revision history, permissions, and built for multiple users',
        'FOOTER': '&copy; 2016, 2017 <b>Paul Hammant</b>. All Rights Reserved',
        'KNOW_MORE': 'MORE INFO?',
        'FEATURES': 'Features',
        'LIST': 'Basic file-sync features',
        'FILE_TYPES': 'Large and small file types',
        'ALL_SORTS': 'Excel Spreadsheets, Word documents, Powerpoint presentation, etc. Movies, music, picts too.',
        'DIRECT': 'Users can setup file sync for a subdirectory of a larger tree',
        'RW_PERMS': 'Multi-user with read and write permissions',
        'RW_PERMS2': 'Permissions can be set at any place in the directory tree for users and groups',
        'SVN': 'Using Subversion means many features come by default',
        'HIST': 'Terabytes of revision history is permanently retained',
        'HIST2': 'Subversion does not have an upper limit of what can be stored in it',
        'POWER_USERS': 'Power users can still use traditional Svn workflows',
        'CLI_TOOLS': 'Like &apos;checkout&apos; and &apos;commit&apos;, as well as batch operations',
        'STILL_READING': 'Less main stream features',
        'X_PLAT': 'Works on Windows, Mac and Linux',
        'EXCEPT': 'Not for iOS or Android, yet',
        'PYTHON': 'Simple Python client (and three Python packages) is the entire installation',
        'NO_SVN': 'No client-side installation of Subversion at all means no &apos;working copy&apos; or .svn folders (or duplicated files)',
        'EXCLUDES': 'Files can be globally excluded from sync operations via their suffix',
        'EXCLUDES2': 'Some applications make a temp backup file while editing, like &apos;.bak&apos;',
        'TESTIMONIALS': 'Testimonials from those using it',
        'TESTIMONIAL_1': 'I have been using this for a year and love it. It is just what I have always wanted',
        'PH': 'Paul Hammant',
        'TESTIMONIAL_2': 'I hope he is going to stop talking about it soon',
        'PH_FRIEND': 'Paul&apos;s friend',
        'GH': 'is open source <a href="https://github.com/paul-hammant/subsyncit">on GitHub</a> (of course). Installation instructions <a href="https://github.com/paul-hammant/subsyncit/blob/master/CLIENT-SETUP.md">here</a>.'
    });

    var userLang = navigator.language || navigator.userLanguage;
    var defaultLanguage = userLang.split('-')[0];
    $translateProvider.preferredLanguage(defaultLanguage);
}]);
