ourApp.config(['$translateProvider', function ($translateProvider) {
    $translateProvider.useSanitizeValueStrategy(null);
    $translateProvider.translations('en', {
        'TAGLINE': 'File sync for the office (or home) that is backed by <strong>Subversion</strong> (your own or cloud based), with revision history, permissions, and built for multiple colleagues (or family members)',
        'FOOTER': '&copy; 2016, 2017 <b>Paul Hammant</b>. All Rights Reserved',
        'KNOW_MORE': 'MORE INFO?',
        'FEATURES': 'There are lots of features',
        'LIST': 'Here is a handy list!',
        'FILE_TYPES': 'Large and small file types',
        'ALL_SORTS': 'Excel Spreadsheets, Word documents, Powerpoint presentation, etc. Movies, music, picts too.',
        'MANY': 'One or thousands of concurrent users',
        'RW_PERMS': 'Read and write permissions for users and groups',
        'RW_PERMS2': 'Permissions, like direct access, at any place in the directory tree',
        'SVN': 'Using Subversion means many features come by default',
        'HIST': 'Terabytes of revision history is permanently retained',
        'HIST2': 'Subversion does not have an upper limit of what can be stored in it',
        'POWER_USERS': 'Power users can still use traditional Svn workflows',
        'CLI_TOOLS': 'Like &apos;checkout&apos; and &apos;commit&apos;, as well as batch operations',
        'STILL_READING': 'Still Reading? Cool, have some more features...',
        'X_PLAT': 'Works on Windows, Mac and Linux',
        'EXCEPT': 'Not for iOS or Android, yet',
        'NO_SVN': 'Subsyncit does not use Subversion at all on the client side',
        'NO_WC': 'That means no &apos;working copy&apos; or .svn folders (or duplicated files)',
        'EXCLUDES': 'Files can be excluded from sync operations via their suffix',
        'EXCLUDES2': 'Some applications make a temp backup file while editing, like &apos;.bak&apos;',
        'TESTIMONIALS': 'Testimonials from those using it',
        'TESTIMONIAL_1': 'I have been using this for a year and love it. It is just what I have always wanted',
        'PH': 'Paul Hammant',
        'TESTIMONIAL_2': 'I hope he is going to stop talking about it soon',
        'PH_FRIEND': 'Paul&apos;s friend',
        'GH': 'is open source on GitHub (of course)'
    });

    $translateProvider.translations('es', {
        'TAGLINE': 'File sync for the office (or home) that is backed by <strong>Subversion</strong> (your own or cloud based), with revision history, permissions, and built for multiple colleagues (or family members)',
        'FOOTER': '&copy; 2016, 2017 <b>Paul Hammant</b>. All Rights Reserved',
        'KNOW_MORE': 'MORE INFO?',
        'FEATURES': 'There are lots of features',
        'LIST': 'Here is a handy list!',
        'FILE_TYPES': 'Large and small file types',
        'ALL_SORTS': 'Excel Spreadsheets, Word documents, Powerpoint presentation, etc. Movies, music, picts too.',
        'MANY': 'One or thousands of concurrent users',
        'RW_PERMS': 'Read and write permissions for users and groups',
        'RW_PERMS2': 'Permissions, like direct access, at any place in the directory tree',
        'SVN': 'Using Subversion means many features come by default',
        'HIST': 'Terabytes of revision history is permanently retained',
        'HIST2': 'Subversion does not have an upper limit of what can be stored in it',
        'POWER_USERS': 'Power users can still use traditional Svn workflows',
        'CLI_TOOLS': 'Like &apos;checkout&apos; and &apos;commit&apos;, as well as batch operations',
        'STILL_READING': 'Still Reading? Cool, have some more features...',
        'X_PLAT': 'Works on Windows, Mac and Linux',
        'EXCEPT': 'Not for iOS or Android, yet',
        'NO_SVN': 'Subsyncit does not use Subversion at all on the client side',
        'NO_WC': 'That means no &apos;working copy&apos; or .svn folders (or duplicated files)',
        'EXCLUDES': 'Files can be excluded from sync operations via their suffix',
        'EXCLUDES2': 'Some applications make a temp backup file while editing, like &apos;.bak&apos;',
        'TESTIMONIALS': 'Testimonials from those using it',
        'TESTIMONIAL_1': 'I have been using this for a year and love it. It is just what I have always wanted',
        'PH': 'Paul Hammant',
        'TESTIMONIAL_2': 'I hope he is going to stop talking about it soon',
        'PH_FRIEND': 'Paul&apos;s friend',
        'GH': 'is open source on GitHub (of course)'
    });

    var userLang = navigator.language || navigator.userLanguage;
    var defaultLanguage = userLang.split('-')[0];
    $translateProvider.preferredLanguage(defaultLanguage);
}]);
